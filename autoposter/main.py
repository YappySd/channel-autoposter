"""Entry point:  python -m autoposter.main
Dry run (collect only, print what would be posted, nothing is sent):  python -m autoposter.main --dry-run
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timedelta

import aiohttp
from dotenv import load_dotenv

from autoposter.adapters import HttpFetcher, TelegramPublisher
from autoposter.config import ConfigError, load_settings, load_sources
from autoposter.core import format_post
from autoposter.service import Autoposter
from autoposter.storage import Storage

log = logging.getLogger("autoposter")


async def amain(dry_run: bool) -> None:
    load_dotenv()
    settings = load_settings()
    sources = load_sources(settings.sources_path)

    def now() -> datetime:
        return datetime.now(settings.timezone).replace(tzinfo=None)

    async with aiohttp.ClientSession() as session:
        fetch = HttpFetcher(session)
        if dry_run:
            storage = Storage()  # in memory: a dry run must not mark anything as seen

            async def show(text: str) -> None:
                print(text, end="\n" + "-" * 40 + "\n")

            poster = Autoposter(storage, sources, settings.schedule, fetch, show, initial_items=settings.initial_items,
                                footer=settings.footer)
            report = await poster.collect(now())
            print(f"Новых: {report.new}, дублей: {report.duplicates}, пропущено архива: {report.skipped_backlog}")
            for _, item in storage.next_queued(5):
                await show(format_post(item, footer=settings.footer))
            return

        storage = Storage(settings.db_path)
        publish = TelegramPublisher(session, settings.bot_token, settings.channel)
        poster = Autoposter(storage, sources, settings.schedule, fetch, publish,
                            posts_per_slot=settings.posts_per_slot, initial_items=settings.initial_items,
                            footer=settings.footer)
        log.info("Автопостинг: %s источников, слоты %s", len(sources),
                 ", ".join(t.strftime("%H:%M") for t in settings.schedule.slots))
        next_collect = now()
        try:
            while True:
                if now() >= next_collect:
                    report = await poster.collect(now())
                    log.info("Сбор: новых %s, дублей %s, пропущено архива %s, ошибок %s", report.new,
                             report.duplicates, report.skipped_backlog, len(report.failed_sources))
                    next_collect = now() + timedelta(minutes=settings.collect_every_min)
                sent = await poster.publish_due(now())
                if sent:
                    log.info("Опубликовано постов: %s", sent)
                await asyncio.sleep(30)
        finally:
            storage.close()


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    try:
        asyncio.run(amain("--dry-run" in sys.argv))
    except ConfigError as exc:
        sys.exit(f"Ошибка настройки: {exc}")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
