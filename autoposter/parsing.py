"""Turn RSS/Atom XML or a plain HTML page into Items (defusedxml + standard library)."""

from __future__ import annotations

import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urljoin

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import ParseError, fromstring

from autoposter.core import Item, plain_title

ATOM = "{http://www.w3.org/2005/Atom}"


class FeedError(ValueError):
    pass


def _date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    try:
        value = parsedate_to_datetime(raw)  # RSS: "Tue, 05 Nov 2030 10:00:00 +0200"
    except (TypeError, ValueError):
        try:
            value = datetime.fromisoformat(raw.replace("Z", "+00:00"))  # Atom: ISO 8601
        except ValueError:
            return None
    return value.replace(tzinfo=None) if value.tzinfo is None else value.astimezone().replace(tzinfo=None)


def _text(node, tag: str) -> str:
    found = node.find(tag)
    return (found.text or "").strip() if found is not None else ""


def parse_feed(xml_text: str, source: str) -> list[Item]:
    """RSS 2.0 or Atom. Items without title and link are skipped."""
    try:
        # defusedxml: feeds come from third-party sites, so entity tricks (XXE, "billion laughs") are refused.
        root = fromstring(xml_text.strip())
    except (ParseError, DefusedXmlException) as exc:
        raise FeedError(f"{source}: not a valid feed") from exc

    items: list[Item] = []
    if root.tag == f"{ATOM}feed":
        for entry in root.findall(f"{ATOM}entry"):
            link = ""
            for node in entry.findall(f"{ATOM}link"):
                if node.get("rel", "alternate") == "alternate":
                    link = node.get("href", "")
                    break
            summary = _text(entry, f"{ATOM}summary") or _text(entry, f"{ATOM}content")
            items.append(Item(source, plain_title(_text(entry, f"{ATOM}title")), link, summary,
                              _date(_text(entry, f"{ATOM}published") or _text(entry, f"{ATOM}updated"))))
    else:
        channel = root.find("channel")
        if channel is None:
            raise FeedError(f"{source}: unknown feed format")
        for node in channel.findall("item"):
            link = _text(node, "link") or _text(node, "guid")
            items.append(Item(source, plain_title(_text(node, "title")), link, _text(node, "description"),
                              _date(_text(node, "pubDate"))))
    return [i for i in items if i.title or i.link]


class _LinkCollector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join("".join(self._text).split())))
            self._href = None


def parse_html_links(page: str, base_url: str, source: str, link_pattern: str, min_title: int = 15) -> list[Item]:
    """For sites without RSS: links whose URL matches `link_pattern` become items.

    Short link texts ("Читать", "Далее") are ignored; the same URL is taken once.
    """
    pattern = re.compile(link_pattern)
    collector = _LinkCollector()
    collector.feed(page)
    seen, items = set(), []
    for href, title in collector.links:
        url = urljoin(base_url, href or "")
        if not pattern.search(url) or len(title) < min_title or url in seen:
            continue
        seen.add(url)
        items.append(Item(source, title, url))
    return items
