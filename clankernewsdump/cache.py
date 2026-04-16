"""SQLite cache for items, summaries, subscriptions, bookmarks, read state, and scrape tracking."""
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_category ON items(category)")
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
    conn.execute(
        """CREATE TABLE IF NOT EXISTS bookmarks (
            url TEXT PRIMARY KEY,
            added_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS read_items (
            url TEXT PRIMARY KEY,
            read_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS custom_sources (
            name TEXT NOT NULL,
            url TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            source_type TEXT NOT NULL DEFAULT 'rss',
            added_at TEXT NOT NULL
        )"""
    )
    return conn


# ---------- summaries ----------


def get_summary(url: str) -> str | None:
    with _conn() as c:
        row = c.execute("SELECT summary FROM summaries WHERE url = ?", (url,)).fetchone()
        return row[0] if row else None


def get_all_summaries(urls: list[str]) -> dict[str, str]:
    if not urls:
        return {}
    with _conn() as c:
        placeholders = ",".join("?" * len(urls))
        rows = c.execute(
            f"SELECT url, summary FROM summaries WHERE url IN ({placeholders})", urls
        ).fetchall()
    return {url: summary for url, summary in rows}


def put_summary(url: str, summary: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO summaries (url, summary, created_at) VALUES (?, ?, ?)",
            (url, summary, datetime.now(timezone.utc).isoformat()),
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
    subs = get_subscriptions()
    if source_name in subs:
        remove_subscription(source_name)
        return False
    add_subscription(source_name)
    return True


# ---------- bookmarks ----------


def get_bookmarks() -> set[str]:
    with _conn() as c:
        rows = c.execute("SELECT url FROM bookmarks").fetchall()
    return {r[0] for r in rows}


def add_bookmark(url: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO bookmarks (url, added_at) VALUES (?, ?)",
            (url, datetime.now(timezone.utc).isoformat()),
        )


def remove_bookmark(url: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM bookmarks WHERE url = ?", (url,))


def toggle_bookmark(url: str) -> bool:
    bookmarks = get_bookmarks()
    if url in bookmarks:
        remove_bookmark(url)
        return False
    add_bookmark(url)
    return True


def get_bookmarked_items() -> list[Item]:
    with _conn() as c:
        rows = c.execute(
            """SELECT i.source, i.category, i.title, i.url, i.published, i.snippet, i.score
            FROM items i INNER JOIN bookmarks b ON i.url = b.url
            ORDER BY b.added_at DESC"""
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


# ---------- read/unread ----------


def get_read_urls() -> set[str]:
    with _conn() as c:
        rows = c.execute("SELECT url FROM read_items").fetchall()
    return {r[0] for r in rows}


def mark_read(url: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO read_items (url, read_at) VALUES (?, ?)",
            (url, datetime.now(timezone.utc).isoformat()),
        )


def mark_unread(url: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM read_items WHERE url = ?", (url,))


# ---------- custom sources ----------


def get_custom_feeds() -> list[tuple[str, str, str]]:
    """Return list of (name, url, category) for custom RSS feeds."""
    with _conn() as c:
        rows = c.execute(
            "SELECT name, url, category FROM custom_sources WHERE source_type = 'rss' ORDER BY name"
        ).fetchall()
    return [(name, url, cat) for name, url, cat in rows]


def get_custom_subreddits() -> list[str]:
    with _conn() as c:
        rows = c.execute(
            "SELECT name FROM custom_sources WHERE source_type = 'subreddit' ORDER BY name"
        ).fetchall()
    return [r[0] for r in rows]


def get_custom_hn_queries() -> list[str]:
    with _conn() as c:
        rows = c.execute(
            "SELECT name FROM custom_sources WHERE source_type = 'hn_query' ORDER BY name"
        ).fetchall()
    return [r[0] for r in rows]


def add_custom_source(name: str, url: str, category: str, source_type: str = "rss") -> bool:
    """Add a custom source. Returns True if newly added, False if already exists."""
    with _conn() as c:
        cur = c.execute(
            "INSERT OR IGNORE INTO custom_sources (name, url, category, source_type, added_at) VALUES (?, ?, ?, ?, ?)",
            (name, url, category, source_type, datetime.now(timezone.utc).isoformat()),
        )
        return cur.rowcount > 0


def remove_custom_source(url_or_name: str) -> bool:
    """Remove a custom source by URL or name. Returns True if removed."""
    with _conn() as c:
        cur = c.execute(
            "DELETE FROM custom_sources WHERE url = ? OR name = ?",
            (url_or_name, url_or_name),
        )
        return cur.rowcount > 0


def get_all_custom_sources() -> list[dict]:
    """Return all custom sources as dicts."""
    with _conn() as c:
        rows = c.execute(
            "SELECT name, url, category, source_type, added_at FROM custom_sources ORDER BY source_type, name"
        ).fetchall()
    return [{"name": n, "url": u, "category": c, "type": t, "added_at": a} for n, u, c, t, a in rows]


# ---------- scrape log ----------


def log_scrape(scrape_date: date, item_count: int) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO scrape_log (scrape_date, completed_at, item_count) VALUES (?, ?, ?)",
            (scrape_date.isoformat(), datetime.now(timezone.utc).isoformat(), item_count),
        )


def get_scraped_dates() -> dict[date, int]:
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
