"""Pure logic: duplicate keys, post text, schedule. No network, no Telegram."""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TELEGRAM_LIMIT = 4096
TRACKING_PARAMS = ("utm_", "fbclid", "gclid", "yclid", "mc_cid", "mc_eid", "ref")


@dataclass(frozen=True)
class Item:
    source: str
    title: str
    link: str
    summary: str = ""
    published: datetime | None = None

    @property
    def key(self) -> str:
        return item_key(self)


def normalize_url(url: str) -> str:
    """Same article, different URL noise -> same string.

    Drops tracking params, #fragment, trailing slash, `www.` and http/https difference.
    """
    parts = urlsplit((url or "").strip())
    host = parts.netloc.lower().removeprefix("www.")
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith(TRACKING_PARAMS)]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("", host, path, urlencode(sorted(query)), ""))


def normalize_title(title: str) -> str:
    text = re.sub(r"[^\w\s]", " ", (title or "").lower())
    return " ".join(text.split())


def item_key(item: Item) -> str:
    """Duplicate key: the normalized link, or the title when there is no link."""
    base = normalize_url(item.link) if item.link else "title:" + normalize_title(item.title)
    return hashlib.sha1(base.encode(), usedforsecurity=False).hexdigest()  # a key, not protection


def title_key(item: Item) -> str:
    """Second key: the same news re-published under a new URL is still a duplicate."""
    return "t:" + hashlib.sha1(normalize_title(item.title).encode(), usedforsecurity=False).hexdigest()


def clean_text(raw: str) -> str:
    """Feed summaries often contain HTML: drop tags, unescape entities, squeeze spaces."""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw or "", flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(html.unescape(text).split())


def plain_title(raw: str) -> str:
    """Titles are plain text: "Цены <выросли>" must keep its brackets, so no tag stripping."""
    return " ".join(html.unescape(raw or "").split())


def shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    if space > limit * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,.;:-") + "…"


def format_post(item: Item, *, summary_limit: int = 300, footer: str = "") -> str:
    """Telegram HTML post: bold title, short summary, link, optional footer."""
    e = html.escape
    parts = [f"<b>{e(plain_title(item.title))}</b>"]
    summary = shorten(clean_text(item.summary), summary_limit)
    if summary:
        parts.append(e(summary))
    # Links come from someone else's feed: only plain web links, never javascript: or similar.
    if item.link and item.link.lower().startswith(("http://", "https://")):
        parts.append(f'<a href="{e(item.link, quote=True)}">Читать полностью</a>')
    if footer:
        parts.append(e(footer))
    text = "\n\n".join(parts)
    if len(text) > TELEGRAM_LIMIT:  # only possible with a huge title or footer
        text = text[: TELEGRAM_LIMIT - 1] + "…"
    return text


# -------------------------------------------------------------- schedule


def parse_slots(raw: str) -> tuple[time, ...]:
    slots = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if not re.fullmatch(r"\d{1,2}:\d{2}", part):
            raise ValueError(f"bad time: {part!r}")
        h, m = map(int, part.split(":"))
        slots.append(time(h, m))
    if not slots:
        raise ValueError("schedule is empty")
    return tuple(sorted(set(slots)))


@dataclass(frozen=True)
class Schedule:
    slots: tuple[time, ...]
    weekdays: frozenset[int] = frozenset(range(7))  # 0 = Monday

    def _slot_times(self, day: date):
        if day.weekday() in self.weekdays:
            for t in self.slots:
                yield datetime.combine(day, t)

    def latest_due(self, last_run: datetime | None, now: datetime) -> datetime | None:
        """The newest slot in (last_run, now], or None.

        If the poster was offline for several slots it publishes once, not a burst.
        On the very first start (last_run is None) nothing is due until the next slot.
        """
        if last_run is None:
            return None
        found = None
        day = last_run.date()
        while day <= now.date():
            for slot in self._slot_times(day):
                if last_run < slot <= now:
                    found = slot
            day += timedelta(days=1)
        return found

    def next_slot(self, now: datetime) -> datetime:
        for offset in range(8):
            for slot in self._slot_times(now.date() + timedelta(days=offset)):
                if slot > now:
                    return slot
        raise ValueError("no slots in a week")
