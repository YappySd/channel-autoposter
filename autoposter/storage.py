"""SQLite: what was already seen, what waits in the queue, what was published."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta

from autoposter.core import Item, item_key, title_key

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen (key TEXT PRIMARY KEY, first_seen TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL, title TEXT NOT NULL, link TEXT NOT NULL, summary TEXT NOT NULL,
    published TEXT, status TEXT NOT NULL DEFAULT 'queued', posted_at TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS state (name TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sources (name TEXT PRIMARY KEY);
"""


class Storage:
    def __init__(self, path: str = ":memory:"):
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._lock = threading.RLock()
        with self._lock:
            self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------ sources

    def is_new_source(self, name: str) -> bool:
        with self._lock:
            return self._conn.execute("SELECT 1 FROM sources WHERE name = ?", (name,)).fetchone() is None

    def mark_source(self, name: str) -> None:
        with self._lock:
            self._conn.execute("INSERT OR IGNORE INTO sources (name) VALUES (?)", (name,))

    # -------------------------------------------------------- duplicates

    def remember(self, item: Item, now: datetime, title_window_days: int = 3) -> bool:
        """Record the item. False if it is a duplicate.

        A link seen once is a duplicate forever. The same title only counts within
        `title_window_days`: daily posts like "Курс валют на сегодня" must still go out.
        """
        link_key, t_key = item_key(item), title_key(item)
        border = (now - timedelta(days=title_window_days)).isoformat()
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                link_known = self._conn.execute("SELECT 1 FROM seen WHERE key = ?", (link_key,)).fetchone()
                title_recent = self._conn.execute(
                    "SELECT 1 FROM seen WHERE key = ? AND first_seen > ?", (t_key, border)
                ).fetchone()
                duplicate = bool(link_known or title_recent)
                self._conn.execute("INSERT OR IGNORE INTO seen (key, first_seen) VALUES (?, ?)", (link_key, now.isoformat()))
                if not duplicate:
                    self._conn.execute("INSERT OR REPLACE INTO seen (key, first_seen) VALUES (?, ?)", (t_key, now.isoformat()))
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
        return not duplicate

    # -------------------------------------------------------------- queue

    def enqueue(self, item: Item) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO queue (key, source, title, link, summary, published) VALUES (?, ?, ?, ?, ?, ?)",
                (item_key(item), item.source, item.title, item.link, item.summary,
                 item.published.isoformat() if item.published else None),
            )

    def next_queued(self, limit: int) -> list[tuple[int, Item]]:
        """Oldest first: by publication date when known, otherwise by arrival."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, source, title, link, summary, published FROM queue WHERE status = 'queued' "
                "ORDER BY COALESCE(published, '9999'), id LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            (rid, Item(src, title, link, summary, datetime.fromisoformat(pub) if pub else None))
            for rid, src, title, link, summary, pub in rows
        ]

    def mark_posted(self, row_id: int, now: datetime) -> None:
        with self._lock:
            self._conn.execute("UPDATE queue SET status = 'posted', posted_at = ? WHERE id = ?", (now.isoformat(), row_id))

    def mark_failed(self, row_id: int, error: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE queue SET status = 'failed', error = ? WHERE id = ?", (error[:300], row_id))

    def count(self, status: str) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM queue WHERE status = ?", (status,)).fetchone()[0]

    # -------------------------------------------------------------- state

    def get_state(self, name: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM state WHERE name = ?", (name,)).fetchone()
        return row[0] if row else None

    def set_state(self, name: str, value: str) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO state (name, value) VALUES (?, ?)", (name, value))
