"""SQLite cache for items, summaries, subscriptions, and scrape tracking."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .models import Item

CACHE_PATH = Path.home() / ".clankernewsdump" / "cache.db"


def _conn() -> sqlite3.Connection:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CACHE_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS summaries (
            url TEXT PRIMARY KEY,
            summary TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS items (
            url TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            published TEXT NOT NULL,
            snippet TEXT,
            score INTEGER DEFAULT 0,
            fetched_at TEXT NOT NULL
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_published ON items(published)")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS subscriptions (
            source_name TEXT PRIMARY KEY,
            added_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS scrape_log (
            scrape_date TEXT NOT NULL,
            completed_at TEXT NOT NULL,
            item_count INTEGER DEFAULT 0,
            PRIMARY KEY (scrape_date)
        )"""
    )
    return conn


# ---------- summaries ----------


def get_summary(url: str) -> str | None:
    with _conn() as c:
        row = c.execute("SELECT summary FROM summaries WHERE url = ?", (url,)).fetchone()
        return row[0] if row else None


def put_summary(url: str, summary: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO summaries (url, summary, created_at) VALUES (?, ?, ?)",
            (url, summary, datetime.utcnow().isoformat()),
        )


# ---------- items ----------


def upsert_items(items: list[Item]) -> int:
    if not items:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    with _conn() as c:
        for it in items:
            if not it.url:
                continue
            cur = c.execute(
                """INSERT OR IGNORE INTO items
                (url, source, category, title, published, snippet, score, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (it.url, it.source, it.category, it.title,
                 it.published.isoformat(), it.snippet, it.score, now),
            )
            if cur.rowcount:
                inserted += 1
            else:
                c.execute(
                    "UPDATE items SET score = MAX(score, ?) WHERE url = ?",
                    (it.score, it.url),
                )
    return inserted


def load_items_in_range(start: date, end: date) -> list[Item]:
    start_iso = datetime(start.year, start.month, start.day, tzinfo=timezone.utc).isoformat()
    end_iso = datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=timezone.utc).isoformat()
    with _conn() as c:
        rows = c.execute(
            """SELECT source, category, title, url, published, snippet, score
            FROM items WHERE published >= ? AND published <= ?
            ORDER BY published DESC""",
            (start_iso, end_iso),
        ).fetchall()
    out: list[Item] = []
    for source, category, title, url, published, snippet, score in rows:
        try:
            pub = datetime.fromisoformat(published)
        except ValueError:
            continue
        out.append(Item(source=source, category=category, title=title, url=url,
                        published=pub, snippet=snippet or "", score=score or 0))
    return out


def load_recent_items(days: int) -> list[Item]:
    end = date.today()
    start = end - timedelta(days=days)
    return load_items_in_range(start, end)


def prune_old_items(days: int = 60) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _conn() as c:
        cur = c.execute("DELETE FROM items WHERE published < ?", (cutoff,))
        return cur.rowcount


# ---------- subscriptions ----------


def get_subscriptions() -> set[str]:
    with _conn() as c:
        rows = c.execute("SELECT source_name FROM subscriptions").fetchall()
    return {r[0] for r in rows}


def add_subscription(source_name: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO subscriptions (source_name, added_at) VALUES (?, ?)",
            (source_name, datetime.now(timezone.utc).isoformat()),
        )


def remove_subscription(source_name: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM subscriptions WHERE source_name = ?", (source_name,))


def toggle_subscription(source_name: str) -> bool:
    """Toggle and return True if now subscribed, False if unsubscribed."""
    subs = get_subscriptions()
    if source_name in subs:
        remove_subscription(source_name)
        return False
    add_subscription(source_name)
    return True


# ---------- scrape log ----------


def log_scrape(scrape_date: date, item_count: int) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO scrape_log (scrape_date, completed_at, item_count) VALUES (?, ?, ?)",
            (scrape_date.isoformat(), datetime.now(timezone.utc).isoformat(), item_count),
        )


def get_scraped_dates() -> dict[date, int]:
    """Return {date: item_count} for all scraped dates."""
    with _conn() as c:
        rows = c.execute("SELECT scrape_date, item_count FROM scrape_log").fetchall()
    out: dict[date, int] = {}
    for d, count in rows:
        try:
            out[date.fromisoformat(d)] = count
        except ValueError:
            continue
    return out


def dates_with_items(start: date, end: date) -> set[date]:
    """Return set of dates that have at least one item in the DB."""
    start_iso = datetime(start.year, start.month, start.day, tzinfo=timezone.utc).isoformat()
    end_iso = datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=timezone.utc).isoformat()
    with _conn() as c:
        rows = c.execute(
            "SELECT DISTINCT substr(published, 1, 10) FROM items WHERE published >= ? AND published <= ?",
            (start_iso, end_iso),
        ).fetchall()
    out: set[date] = set()
    for (d,) in rows:
        try:
            out.add(date.fromisoformat(d))
        except ValueError:
            continue
    return out
