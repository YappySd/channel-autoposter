import json
from datetime import time

import pytest

from autoposter.config import ConfigError, load_settings, load_sources

BASE = {"BOT_TOKEN": "1:x", "CHANNEL_ID": "@my_channel"}


def test_defaults():
    s = load_settings(BASE)
    assert s.schedule.slots == (time(9), time(13), time(18))
    assert s.schedule.weekdays == frozenset(range(7))
    assert s.posts_per_slot == 1 and s.initial_items == 3


def test_weekdays_and_numeric_channel():
    s = load_settings({**BASE, "CHANNEL_ID": "-1001234567890", "WEEKDAYS": "пн, ср,пт", "SCHEDULE": "10:00"})
    assert s.schedule.weekdays == {0, 2, 4} and s.schedule.slots == (time(10),)


@pytest.mark.parametrize(
    "key, value",
    [("BOT_TOKEN", ""), ("CHANNEL_ID", "my_channel"), ("SCHEDULE", "утром"), ("WEEKDAYS", "mon"),
     ("POSTS_PER_SLOT", "0"), ("POSTS_PER_SLOT", "два")],
)
def test_bad_settings(key, value):
    with pytest.raises(ConfigError):
        load_settings({**BASE, key: value})


def write(tmp_path, data):
    path = tmp_path / "sources.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_sources_file(tmp_path):
    path = write(tmp_path, {"sources": [
        {"name": "news", "url": "https://news.example/rss"},
        {"name": "site", "url": "https://site.example/", "type": "html", "link_pattern": r"/news/\d+"},
    ]})
    sources = load_sources(path)
    assert [s.kind for s in sources] == ["rss", "html"]


@pytest.mark.parametrize(
    "sources",
    [
        [],
        [{"name": "a", "url": "ftp://x"}],
        [{"name": "a", "url": "https://x"}, {"name": "a", "url": "https://y"}],
        [{"name": "a", "url": "https://x", "type": "html"}],
        [{"name": "a", "url": "https://x", "type": "html", "link_pattern": "("}],
        [{"name": "a", "url": "https://x", "type": "telegram"}],
    ],
)
def test_bad_sources(tmp_path, sources):
    with pytest.raises(ConfigError):
        load_sources(write(tmp_path, {"sources": sources}))


def test_missing_and_broken_files(tmp_path):
    with pytest.raises(ConfigError):
        load_sources(tmp_path / "none.json")
    broken = tmp_path / "b.json"
    broken.write_text("{", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_sources(broken)


def test_example_sources_file_is_valid():
    from pathlib import Path

    sources = load_sources(Path(__file__).resolve().parent.parent / "sources.example.json")
    assert [s.kind for s in sources] == ["rss", "html"]
