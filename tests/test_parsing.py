from datetime import datetime

import pytest

from autoposter.parsing import FeedError, parse_feed, parse_html_links
from tests.fixtures import ATOM, BILLION_LAUGHS, HTML, RSS


def test_rss():
    items = parse_feed(RSS, "news")
    assert [i.title for i in items] == ["Третья новость", "Вторая новость", "Первая новость"]
    assert items[0].link == "https://news.example/3?utm_source=rss"
    assert items[0].published is not None and items[0].published > items[1].published
    assert items[0].source == "news"


def test_atom_takes_alternate_link():
    [item] = parse_feed(ATOM, "blog")
    assert item.link == "https://blog.example/post-1"
    assert item.summary == "Кратко о записи"
    assert isinstance(item.published, datetime)


@pytest.mark.parametrize("bad", ["", "not xml", "<html><body></body></html>"])
def test_broken_feed_raises(bad):
    with pytest.raises(FeedError):
        parse_feed(bad, "x")


def test_entity_expansion_is_refused():
    with pytest.raises(FeedError):
        parse_feed(BILLION_LAUGHS, "evil")


def test_html_links_by_pattern():
    items = parse_html_links(HTML, "https://site.example/news/", "site", r"site\.example/news/\d{4}/")
    assert [i.title for i in items] == ["Обновление сервиса: что изменилось", "Новый тариф для малого бизнеса"]
    assert items[0].link == "https://site.example/news/2030/01/07/obnovlenie-servisa"


def test_title_keeps_angle_brackets():
    feed = '<rss><channel><item><title>Цены &lt;выросли&gt; &amp;amp; упали</title><link>https://x/1</link></item></channel></rss>'
    assert parse_feed(feed, "x")[0].title == "Цены <выросли> & упали"
