"""Collect -> deduplicate -> queue -> publish on schedule.

Network and Telegram are passed in as plain async functions, so tests use stubs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable

from autoposter.core import Item, Schedule, format_post
from autoposter.parsing import FeedError, parse_feed, parse_html_links
from autoposter.storage import Storage

log = logging.getLogger(__name__)

Fetch = Callable[[str], Awaitable[str]]
Publish = Callable[[str], Awaitable[None]]


class RejectedPost(Exception):
    """Telegram refused this exact post (bad HTML, too long). Retrying will not help."""


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    kind: str = "rss"          # "rss" (RSS/Atom) or "html" (links on a page)
    link_pattern: str = ""     # for "html": regex the article URL must match


@dataclass
class CollectReport:
    new: int = 0
    duplicates: int = 0
    skipped_backlog: int = 0
    failed_sources: tuple[str, ...] = ()


class Autoposter:
    def __init__(self, storage: Storage, sources: list[Source], schedule: Schedule, fetch: Fetch, publish: Publish,
                 *, posts_per_slot: int = 1, initial_items: int = 3, summary_limit: int = 300, footer: str = ""):
        self.storage = storage
        self.sources = sources
        self.schedule = schedule
        self.fetch = fetch
        self.publish = publish
        self.posts_per_slot = posts_per_slot
        self.initial_items = initial_items
        self.summary_limit = summary_limit
        self.footer = footer

    def _parse(self, source: Source, body: str) -> list[Item]:
        if source.kind == "html":
            return parse_html_links(body, source.url, source.name, source.link_pattern)
        return parse_feed(body, source.name)

    async def collect(self, now: datetime) -> CollectReport:
        report = CollectReport()
        failed = []
        for source in self.sources:
            try:
                items = self._parse(source, await self.fetch(source.url))
            except (FeedError, OSError, TimeoutError) as exc:
                # One broken site must not stop the others.
                log.warning("Источник %s недоступен: %s", source.name, exc)
                failed.append(source.name)
                continue

            first_time = self.storage.is_new_source(source.name)
            # Feeds list newest first; we post oldest first, so walk them reversed.
            ordered = sorted(items, key=lambda i: i.published or datetime.min) if any(i.published for i in items) \
                else list(reversed(items))
            fresh_from = len(ordered) - self.initial_items if first_time else 0
            for index, item in enumerate(ordered):
                if not self.storage.remember(item, now):
                    report.duplicates += 1
                elif index < fresh_from:
                    # A new source would otherwise dump its whole archive into the channel.
                    report.skipped_backlog += 1
                else:
                    self.storage.enqueue(item)
                    report.new += 1
            self.storage.mark_source(source.name)
        report.failed_sources = tuple(failed)
        return report

    async def publish_due(self, now: datetime) -> int:
        """Publish if a slot passed since the last check. Returns the number of posts sent."""
        raw = self.storage.get_state("last_check")
        last = datetime.fromisoformat(raw) if raw else None
        self.storage.set_state("last_check", now.isoformat())
        if self.schedule.latest_due(last, now) is None:
            return 0
        return await self.publish_now(now, self.posts_per_slot)

    async def publish_now(self, now: datetime, limit: int) -> int:
        sent = 0
        for row_id, item in self.storage.next_queued(limit):
            text = format_post(item, summary_limit=self.summary_limit, footer=self.footer)
            try:
                await self.publish(text)
            except RejectedPost as exc:
                # Skip it so one broken post does not block the queue forever.
                log.warning("Telegram отклонил пост: %s", exc)
                self.storage.mark_failed(row_id, str(exc))
                continue
            except Exception as exc:  # noqa: BLE001 - network/limits: keep it queued, try next slot
                log.warning("Публикация отложена: %s", type(exc).__name__)
                break
            self.storage.mark_posted(row_id, now)
            sent += 1
        return sent
