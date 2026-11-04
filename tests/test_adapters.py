"""aiohttp adapters against a local stub server that plays both a news site and the Bot API."""

import asyncio

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from autoposter.adapters import HttpFetcher, TelegramPublisher
from autoposter.service import RejectedPost
from tests.fixtures import RSS

TOKEN = "123456:TEST-not-a-real-token"
SENT = web.AppKey("sent", list)


def stub_app(answers):
    """answers: list of Bot API JSON replies, returned in order."""
    app = web.Application()
    app[SENT] = []

    async def feed(_):
        return web.Response(text=RSS, content_type="application/rss+xml", charset="utf-8")

    async def missing(_):
        return web.Response(status=404)

    async def big(_):
        return web.Response(body=b"x" * 2000)

    async def send(request):
        app[SENT].append((request.match_info["token"], await request.json()))
        return web.json_response(answers.pop(0))

    app.router.add_get("/rss", feed)
    app.router.add_get("/missing", missing)
    app.router.add_get("/big", big)
    app.router.add_post("/bot{token}/sendMessage", send)
    return app


async def with_server(answers, scenario):
    app = stub_app(answers)
    server = TestServer(app)
    await server.start_server()
    try:
        async with aiohttp.ClientSession() as session:
            return await scenario(session, str(server.make_url("")).rstrip("/"), app)
    finally:
        await server.close()


def test_fetcher_reads_feed_and_reports_errors():
    async def scenario(session, base, _):
        fetch = HttpFetcher(session, max_bytes=1000)
        assert "Третья новость" in await fetch(base + "/rss")
        with pytest.raises(OSError):
            await fetch(base + "/missing")
        with pytest.raises(OSError):
            await fetch(base + "/big")
        with pytest.raises(OSError):
            await fetch("http://127.0.0.1:1/nothing")

    asyncio.run(with_server([], scenario))


def test_publisher_sends_html_to_channel():
    async def scenario(session, base, app):
        publish = TelegramPublisher(session, TOKEN, "@my_channel", api_base=base)
        await publish("<b>Пост</b>")
        token, payload = app[SENT][0]
        assert token == TOKEN
        assert payload["chat_id"] == "@my_channel" and payload["parse_mode"] == "HTML"

    asyncio.run(with_server([{"ok": True, "result": {}}], scenario))


def test_publisher_maps_errors():
    answers = [
        {"ok": False, "error_code": 400, "description": "Bad Request: can't parse entities"},
        {"ok": False, "error_code": 403, "description": "bot is not a member of the channel chat"},
    ]

    async def scenario(session, base, _):
        publish = TelegramPublisher(session, TOKEN, "@c", api_base=base)
        with pytest.raises(RejectedPost):
            await publish("x")
        with pytest.raises(ConnectionError):
            await publish("x")

    asyncio.run(with_server(answers, scenario))


def test_publisher_waits_once_on_flood_limit():
    answers = [{"ok": False, "error_code": 429, "parameters": {"retry_after": 0}}, {"ok": True, "result": {}}]

    async def scenario(session, base, app):
        await TelegramPublisher(session, TOKEN, "@c", api_base=base)("x")
        assert len(app[SENT]) == 2

    asyncio.run(with_server(answers, scenario))


def test_main_module_imports():
    import autoposter.main  # noqa: F401
