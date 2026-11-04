"""Network adapters on aiohttp: download a source, post to a channel via Bot API.

`api_base` is a parameter so tests can point it at a local stub server.
"""

from __future__ import annotations

import asyncio

import aiohttp

from autoposter.service import RejectedPost

USER_AGENT = "channel-autoposter/1.0 (+https://github.com/YappySd/channel-autoposter)"


class HttpFetcher:
    def __init__(self, session: aiohttp.ClientSession, timeout: float = 20, max_bytes: int = 5_000_000):
        self.session = session
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.max_bytes = max_bytes

    async def __call__(self, url: str) -> str:
        try:
            async with self.session.get(url, timeout=self.timeout, headers={"User-Agent": USER_AGENT}) as resp:
                if resp.status != 200:
                    raise OSError(f"HTTP {resp.status}")
                body = await resp.content.read(self.max_bytes + 1)
        except aiohttp.ClientError as exc:
            raise OSError(type(exc).__name__) from exc
        if len(body) > self.max_bytes:
            raise OSError("response too large")
        return body.decode(resp.charset or "utf-8", errors="replace")


class TelegramPublisher:
    def __init__(self, session: aiohttp.ClientSession, token: str, channel: str,
                 api_base: str = "https://api.telegram.org", disable_preview: bool = False):
        self.session = session
        self.url = f"{api_base}/bot{token}/sendMessage"
        self.channel = channel
        self.disable_preview = disable_preview

    async def __call__(self, text: str, _retry: bool = True) -> None:
        payload = {
            "chat_id": self.channel,
            "text": text,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": self.disable_preview},
        }
        async with self.session.post(self.url, json=payload) as resp:
            data = await resp.json(content_type=None)
        if data.get("ok"):
            return
        code = data.get("error_code")
        if code == 429 and _retry:
            # Telegram says how long to wait; wait once, then give up until the next slot.
            await asyncio.sleep(min(int(data.get("parameters", {}).get("retry_after", 1)), 60))
            return await self(text, _retry=False)
        if code == 400:
            raise RejectedPost(data.get("description", "bad request"))
        # 401/403 (wrong token, bot not admin) and 5xx: keep the post in the queue.
        raise ConnectionError(f"Telegram error {code}: {data.get('description', '')}")
