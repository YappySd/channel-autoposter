import asyncio
from datetime import datetime, time, timedelta

from autoposter.core import Item, Schedule
from autoposter.service import Autoposter, RejectedPost, Source
from autoposter.storage import Storage
from tests.fixtures import RSS, rss_with

NOW = datetime(2030, 1, 7, 8, 0)
SCHED = Schedule((time(9), time(13), time(18)))


class Web:
    """Stub internet: url -> body, or an exception to raise."""

    def __init__(self, pages):
        self.pages = pages

    async def __call__(self, url):
        page = self.pages[url]
        if isinstance(page, Exception):
            raise page
        return page


class Channel:
    def __init__(self):
        self.posts = []
        self.fail_with = None

    async def __call__(self, text):
        if self.fail_with:
            raise self.fail_with
        self.posts.append(text)


def make(pages, sources=None, **kw):
    channel = Channel()
    sources = sources or [Source("news", "https://news.example/rss")]
    poster = Autoposter(Storage(), sources, SCHED, Web(pages), channel, **kw)
    return poster, channel


def run(coro):
    return asyncio.run(coro)


def test_first_run_takes_only_recent_items():
    poster, _ = make({"https://news.example/rss": rss_with(*[f"Новость {i}" for i in range(10)])}, initial_items=3)
    report = run(poster.collect(NOW))
    assert report.new == 3 and report.skipped_backlog == 7
    queued = [i.title for _, i in poster.storage.next_queued(10)]
    assert queued == ["Новость 2", "Новость 1", "Новость 0"]  # oldest of the three first


def test_repeated_collect_finds_no_duplicates():
    poster, _ = make({"https://news.example/rss": RSS})
    run(poster.collect(NOW))
    report = run(poster.collect(NOW + timedelta(minutes=15)))
    assert report.new == 0 and report.duplicates == 3


def test_new_item_after_first_run_is_queued():
    pages = {"https://news.example/rss": rss_with("Старая")}
    poster, _ = make(pages)
    run(poster.collect(NOW))
    pages["https://news.example/rss"] = rss_with("Свежая", "Старая")
    report = run(poster.collect(NOW + timedelta(minutes=15)))
    assert report.new == 1 and report.duplicates == 1


def test_same_news_from_two_sources_is_posted_once():
    sources = [Source("a", "https://a.example/rss"), Source("b", "https://b.example/rss")]
    pages = {
        "https://a.example/rss": rss_with("Курс гривны укрепился", base="https://a.example/"),
        "https://b.example/rss": rss_with("Курс гривны укрепился!", base="https://b.example/"),
    }
    poster, _ = make(pages, sources)
    report = run(poster.collect(NOW))
    assert report.new == 1 and report.duplicates == 1


def test_same_title_is_allowed_again_after_window():
    pages = {"https://news.example/rss": rss_with("Курс валют на сегодня", base="https://news.example/d1/")}
    poster, _ = make(pages)
    run(poster.collect(NOW))
    pages["https://news.example/rss"] = rss_with("Курс валют на сегодня", base="https://news.example/d2/")
    assert run(poster.collect(NOW + timedelta(days=1))).duplicates == 1
    pages["https://news.example/rss"] = rss_with("Курс валют на сегодня", base="https://news.example/d5/")
    assert run(poster.collect(NOW + timedelta(days=5))).new == 1


def test_broken_source_does_not_stop_others():
    sources = [Source("down", "https://down.example/rss"), Source("news", "https://news.example/rss")]
    poster, _ = make({"https://down.example/rss": OSError("timeout"), "https://news.example/rss": RSS}, sources)
    report = run(poster.collect(NOW))
    assert report.failed_sources == ("down",) and report.new == 3


def test_invalid_feed_counts_as_failed_source():
    poster, _ = make({"https://news.example/rss": "<html>сайт сломался</html>"})
    assert run(poster.collect(NOW)).failed_sources == ("news",)


def test_html_source():
    page = '<a href="/n/1">Первая длинная новость сайта</a><a href="/n/2">Вторая длинная новость сайта</a>'
    sources = [Source("site", "https://site.example/", "html", r"/n/\d+")]
    poster, _ = make({"https://site.example/": page}, sources)
    assert run(poster.collect(NOW)).new == 2


def test_publishes_only_on_schedule_and_in_order():
    poster, channel = make({"https://news.example/rss": RSS}, posts_per_slot=2)
    run(poster.collect(NOW))
    assert run(poster.publish_due(NOW)) == 0            # first check only remembers the time
    assert run(poster.publish_due(NOW.replace(hour=8, minute=59))) == 0
    assert run(poster.publish_due(NOW.replace(hour=9, minute=0))) == 2
    assert "Первая новость" in channel.posts[0] and "Вторая новость" in channel.posts[1]
    assert run(poster.publish_due(NOW.replace(hour=9, minute=30))) == 0
    assert run(poster.publish_due(NOW.replace(hour=13, minute=0))) == 1
    assert poster.storage.count("posted") == 3


def test_downtime_does_not_flood_channel():
    poster, channel = make({"https://news.example/rss": RSS}, posts_per_slot=1)
    run(poster.collect(NOW))
    run(poster.publish_due(NOW))
    assert run(poster.publish_due(NOW + timedelta(days=2))) == 1  # six slots missed, one post


def test_network_error_keeps_post_queued():
    poster, channel = make({"https://news.example/rss": RSS})
    run(poster.collect(NOW))
    channel.fail_with = ConnectionError("telegram down")
    assert run(poster.publish_now(NOW, 1)) == 0
    assert poster.storage.count("queued") == 3
    channel.fail_with = None
    assert run(poster.publish_now(NOW, 1)) == 1


def test_rejected_post_is_skipped_not_blocking():
    poster, channel = make({"https://news.example/rss": RSS})
    run(poster.collect(NOW))
    calls = {"n": 0}

    async def picky(text):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RejectedPost("can't parse entities")
        channel.posts.append(text)

    poster.publish = picky
    assert run(poster.publish_now(NOW, 2)) == 1
    assert poster.storage.count("failed") == 1 and "Вторая новость" in channel.posts[0]


def test_state_survives_restart(tmp_path):
    db = str(tmp_path / "a.db")
    first = Autoposter(Storage(db), [Source("news", "https://news.example/rss")], SCHED, Web({"https://news.example/rss": RSS}), Channel())
    run(first.collect(NOW))
    first.storage.close()
    second = Autoposter(Storage(db), [Source("news", "https://news.example/rss")], SCHED, Web({"https://news.example/rss": RSS}), Channel())
    assert run(second.collect(NOW)).duplicates == 3


def test_storage_queue_order_without_dates():
    storage = Storage()
    for title in ("b", "a"):
        storage.enqueue(Item("s", title, f"https://x/{title}"))
    assert [i.title for _, i in storage.next_queued(5)] == ["b", "a"]
