from datetime import datetime, time

import pytest

from autoposter.core import (
    TELEGRAM_LIMIT,
    Item,
    Schedule,
    clean_text,
    format_post,
    item_key,
    normalize_url,
    parse_slots,
    shorten,
    title_key,
)


@pytest.mark.parametrize(
    "a, b",
    [
        ("https://site.ua/post/1", "https://site.ua/post/1/"),
        ("https://site.ua/post/1", "http://www.site.ua/post/1"),
        ("https://site.ua/post/1", "https://site.ua/post/1?utm_source=tg&utm_medium=x"),
        ("https://site.ua/post/1", "https://site.ua/post/1#comments"),
        ("https://site.ua/p?id=5&b=2", "https://site.ua/p?b=2&id=5&fbclid=abc"),
    ],
)
def test_same_article_same_url(a, b):
    assert normalize_url(a) == normalize_url(b)


def test_different_articles_differ():
    assert normalize_url("https://site.ua/p?id=5") != normalize_url("https://site.ua/p?id=6")


def test_keys():
    a = Item("s", "Новость дня!", "https://site.ua/1?utm_source=x")
    b = Item("other", "Новость  дня", "https://site.ua/1")
    assert item_key(a) == item_key(b)
    assert title_key(a) == title_key(b)
    assert item_key(Item("s", "Без ссылки", "")) == item_key(Item("s", "без ссылки!", ""))


def test_clean_text_strips_html():
    assert clean_text("<p>Привет &amp; <b>мир</b></p><script>alert(1)</script>") == "Привет & мир"


def test_shorten_at_word_boundary():
    text = "слово " * 100
    short = shorten(text.strip(), 50)
    assert len(short) <= 50 and short.endswith("…") and not short[:-1].endswith(" ")
    assert shorten("коротко", 50) == "коротко"


def test_post_format_escapes_and_links():
    item = Item("s", "Цены <выросли> & упали", "https://site.ua/a?x=1&y=2", "<p>Подробности</p>")
    post = format_post(item, footer="@my_channel")
    assert post.startswith("<b>Цены &lt;выросли&gt; &amp; упали</b>")
    assert '<a href="https://site.ua/a?x=1&amp;y=2">Читать полностью</a>' in post
    assert post.endswith("@my_channel")


def test_post_never_exceeds_telegram_limit():
    item = Item("s", "Т" * 5000, "https://site.ua/1", "x" * 5000)
    assert len(format_post(item)) <= TELEGRAM_LIMIT
    assert len(format_post(Item("s", "t", "", "слово " * 1000), summary_limit=300)) < 400


def test_parse_slots():
    assert parse_slots("18:00, 9:00,13:30,9:00") == (time(9), time(13, 30), time(18))
    for bad in ("", "9", "25", "9-00"):
        with pytest.raises(ValueError):
            parse_slots(bad)


SCHED = Schedule((time(9), time(13), time(18)))


def test_first_start_waits_for_next_slot():
    assert SCHED.latest_due(None, datetime(2030, 1, 7, 13, 5)) is None


def test_slot_is_due_once():
    assert SCHED.latest_due(datetime(2030, 1, 7, 12, 59), datetime(2030, 1, 7, 13, 0)) == datetime(2030, 1, 7, 13)
    assert SCHED.latest_due(datetime(2030, 1, 7, 13, 0), datetime(2030, 1, 7, 13, 1)) is None


def test_downtime_publishes_once_not_a_burst():
    # Offline from Monday 08:00 to Tuesday 10:00: four slots missed, only the newest counts.
    assert SCHED.latest_due(datetime(2030, 1, 7, 8), datetime(2030, 1, 8, 10)) == datetime(2030, 1, 8, 9)


def test_weekdays_only():
    weekdays = Schedule((time(9),), frozenset(range(5)))
    saturday = datetime(2030, 1, 12, 8)
    assert weekdays.latest_due(saturday, datetime(2030, 1, 12, 23)) is None
    assert weekdays.next_slot(saturday) == datetime(2030, 1, 14, 9)  # Monday


def test_next_slot_same_day_and_tomorrow():
    assert SCHED.next_slot(datetime(2030, 1, 7, 10)) == datetime(2030, 1, 7, 13)
    assert SCHED.next_slot(datetime(2030, 1, 7, 18)) == datetime(2030, 1, 8, 9)
