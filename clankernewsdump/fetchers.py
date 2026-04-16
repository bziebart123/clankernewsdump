"""Per-source fetchers. Exposes both per-source helpers and an incremental
generator that yields (source_name, new_items_from_this_source) one at a time,
so callers can update a UI or persist as work progresses."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Iterator
from urllib.parse import quote_plus

import feedparser
import httpx
from dateutil import parser as dateparser

from .models import Item
from .sources import (
    ARXIV_CATEGORIES,
    HN_QUERIES,
    RSS_FEEDS,
    SUBREDDITS,
)

UA = "clankernewsdump/0.1 (+https://github.com/brianziebart)"
HEADERS = {"User-Agent": UA}
TIMEOUT = 20.0


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return _to_utc(dateparser.parse(raw))
    except (ValueError, TypeError):
        return None


# ---------- Per-source fetchers ----------


MIN_WORDS_BLOG = 40  # skip low-substance blog posts (bookmarks, quotes, etc.)


def _word_count(html: str) -> int:
    """Rough word count after stripping HTML."""
    import re
    text = re.sub(r"<[^>]+>", " ", html)
    return len(text.split())


def fetch_one_rss(name: str, url: str, category: str, since: datetime) -> list[Item]:
    try:
        resp = httpx.get(url, headers=HEADERS, timeout=TIMEOUT, follow_redirects=True)
        feed = feedparser.parse(resp.content)
    except Exception:
        return []
    out: list[Item] = []
    for entry in feed.entries[:40]:
        published = None
        for field in ("published", "updated", "created"):
            if getattr(entry, field, None):
                published = _parse_date(getattr(entry, field))
                if published:
                    break
        if not published or published < since:
            continue
        snippet = getattr(entry, "summary", "") or getattr(entry, "description", "")
        if category in ("blog", "newsletter") and _word_count(snippet) < MIN_WORDS_BLOG:
            continue
        out.append(
            Item(
                source=name,
                category=category,
                title=getattr(entry, "title", "(untitled)"),
                url=getattr(entry, "link", ""),
                published=published,
                snippet=snippet[:1500],
            )
        )
    return out


def fetch_one_hn_query(query: str, since: datetime) -> list[Item]:
    since_ts = int(since.timestamp())
    url = (
        "https://hn.algolia.com/api/v1/search"
        f"?query={quote_plus(query)}&tags=story&numericFilters=created_at_i>{since_ts},points>50"
        "&hitsPerPage=30"
    )
    try:
        data = httpx.get(url, headers=HEADERS, timeout=TIMEOUT).json()
    except Exception:
        return []
    out: list[Item] = []
    for hit in data.get("hits", []):
        link = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
        created = datetime.fromtimestamp(hit.get("created_at_i", 0), tz=timezone.utc)
        out.append(
            Item(
                source=f"HN: {query}",
                category="hn",
                title=hit.get("title", "(untitled)"),
                url=link,
                published=created,
                snippet=(hit.get("story_text") or "")[:800],
                score=hit.get("points", 0),
            )
        )
    return out


def fetch_one_subreddit(sub: str, since: datetime) -> list[Item]:
    url = f"https://www.reddit.com/r/{sub}/top.json?t=week&limit=30"
    try:
        data = httpx.get(url, headers=HEADERS, timeout=TIMEOUT, follow_redirects=True).json()
    except Exception:
        return []
    out: list[Item] = []
    for child in data.get("data", {}).get("children", []):
        d = child.get("data", {})
        created = datetime.fromtimestamp(d.get("created_utc", 0), tz=timezone.utc)
        if created < since:
            continue
        score = d.get("score", 0)
        if score < 50:
            continue
        permalink = d.get("permalink", "")
        ext_url = d.get("url_overridden_by_dest") or f"https://www.reddit.com{permalink}"
        out.append(
            Item(
                source=f"r/{sub}",
                category="reddit",
                title=d.get("title", "(untitled)"),
                url=ext_url,
                published=created,
                snippet=(d.get("selftext") or "")[:800],
                score=score,
            )
        )
    return out


def fetch_one_arxiv(cat: str, since: datetime) -> list[Item]:
    url = (
        "http://export.arxiv.org/api/query"
        f"?search_query=cat:{cat}&sortBy=submittedDate&sortOrder=descending&max_results=50"
    )
    try:
        resp = httpx.get(url, headers=HEADERS, timeout=TIMEOUT)
        feed = feedparser.parse(resp.content)
    except Exception:
        return []
    out: list[Item] = []
    for entry in feed.entries:
        published = _parse_date(getattr(entry, "published", None))
        if not published or published < since:
            continue
        out.append(
            Item(
                source=f"arXiv {cat}",
                category="arxiv",
                title=getattr(entry, "title", "(untitled)").replace("\n", " ").strip(),
                url=getattr(entry, "link", ""),
                published=published,
                snippet=getattr(entry, "summary", "")[:1500],
            )
        )
    return out


# ---------- Plan + iterator ----------


def build_plan(sources: Iterable[str] | None = None) -> list[tuple[str, Callable[[datetime], list[Item]]]]:
    """Return an ordered list of (label, fetch_fn) tasks. Each fetch_fn takes `since`."""
    sources = set(sources) if sources else {"rss", "hn", "reddit", "arxiv"}
    plan: list[tuple[str, Callable[[datetime], list[Item]]]] = []
    if "rss" in sources:
        for name, url, category in RSS_FEEDS:
            plan.append((name, lambda since, n=name, u=url, c=category: fetch_one_rss(n, u, c, since)))
    if "hn" in sources:
        for q in HN_QUERIES:
            plan.append((f"HN:{q}", lambda since, q=q: fetch_one_hn_query(q, since)))
    if "reddit" in sources:
        for sub in SUBREDDITS:
            plan.append((f"r/{sub}", lambda since, s=sub: fetch_one_subreddit(s, since)))
    if "arxiv" in sources:
        for cat in ARXIV_CATEGORIES:
            plan.append((f"arXiv {cat}", lambda since, c=cat: fetch_one_arxiv(c, since)))
    return plan


def fetch_incrementally(
    days: int, sources: Iterable[str] | None = None
) -> Iterator[tuple[str, int, int, list[Item]]]:
    """Yields (label, index, total, items) tuples as each source completes."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    plan = build_plan(sources)
    total = len(plan)
    for i, (label, fn) in enumerate(plan, start=1):
        try:
            items = fn(since)
        except Exception:
            items = []
        yield label, i, total, items


def fetch_all(days: int, sources: Iterable[str] | None = None) -> list[Item]:
    """Blocking one-shot fetch (used by the flat dump mode)."""
    out: list[Item] = []
    for _label, _i, _total, items in fetch_incrementally(days, sources):
        out.extend(items)
    return out
