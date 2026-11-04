"""Settings from .env and the list of sources from sources.json."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from autoposter.core import Schedule, parse_slots
from autoposter.service import Source

WEEKDAYS = {"пн": 0, "вт": 1, "ср": 2, "чт": 3, "пт": 4, "сб": 5, "вс": 6}


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    bot_token: str
    channel: str
    schedule: Schedule
    timezone: ZoneInfo
    posts_per_slot: int
    collect_every_min: int
    initial_items: int
    footer: str
    db_path: str
    sources_path: str


def parse_weekdays(raw: str) -> frozenset[int]:
    raw = raw.strip().lower()
    if not raw:
        return frozenset(range(7))
    try:
        return frozenset(WEEKDAYS[d.strip()] for d in raw.split(",") if d.strip())
    except KeyError as exc:
        raise ConfigError(f"WEEKDAYS: неизвестный день {exc}; пишите пн,вт,ср,чт,пт,сб,вс") from exc


def _int(env, name: str, default: int, minimum: int = 1) -> int:
    try:
        value = int(env.get(name, default))
    except ValueError as exc:
        raise ConfigError(f"{name} должно быть числом") from exc
    if value < minimum:
        raise ConfigError(f"{name} должно быть не меньше {minimum}")
    return value


def load_settings(env=os.environ) -> Settings:
    token = env.get("BOT_TOKEN", "").strip()
    if not token:
        raise ConfigError("BOT_TOKEN не задан. Скопируйте .env.example в .env.")
    channel = env.get("CHANNEL_ID", "").strip()
    if not re.fullmatch(r"@\w{4,}|-100\d+", channel):
        raise ConfigError("CHANNEL_ID: @имя_канала или числовой id вида -100...")
    try:
        slots = parse_slots(env.get("SCHEDULE", "09:00,13:00,18:00"))
    except ValueError as exc:
        raise ConfigError(f"SCHEDULE: {exc}") from exc
    return Settings(
        bot_token=token,
        channel=channel,
        schedule=Schedule(slots, parse_weekdays(env.get("WEEKDAYS", ""))),
        timezone=ZoneInfo(env.get("TIMEZONE", "Europe/Kyiv")),
        posts_per_slot=_int(env, "POSTS_PER_SLOT", 1),
        collect_every_min=_int(env, "COLLECT_EVERY_MIN", 15),
        initial_items=_int(env, "INITIAL_ITEMS", 3, minimum=0),
        footer=env.get("FOOTER", ""),
        db_path=env.get("DB_PATH", "autoposter.db"),
        sources_path=env.get("SOURCES_PATH", "sources.json"),
    )


def load_sources(path: str | Path) -> list[Source]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Нет файла {path}. Скопируйте sources.example.json в sources.json.") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path}: ошибка JSON в строке {exc.lineno}") from exc
    sources, names = [], set()
    for i, raw in enumerate(data.get("sources", []), 1):
        name, url, kind = raw.get("name", "").strip(), raw.get("url", "").strip(), raw.get("type", "rss")
        if not name or not url.startswith(("http://", "https://")):
            raise ConfigError(f"Источник №{i}: нужны name и url (http/https)")
        if name in names:
            raise ConfigError(f"Источник {name!r} указан дважды")
        if kind not in ("rss", "html"):
            raise ConfigError(f"Источник {name!r}: type должен быть rss или html")
        pattern = raw.get("link_pattern", "")
        if kind == "html":
            if not pattern:
                raise ConfigError(f"Источник {name!r}: для type=html нужен link_pattern")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ConfigError(f"Источник {name!r}: link_pattern не регулярное выражение") from exc
        names.add(name)
        sources.append(Source(name, url, kind, pattern))
    if not sources:
        raise ConfigError(f"{path}: список sources пуст")
    return sources
