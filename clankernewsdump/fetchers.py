"""Per-source fetchers with retry logic and HTTP caching (ETag/Last-Modified).

Exposes both per-source helpers and an incremental generator that yields
(source_name, new_items_from_this_source) one at a time, so callers can
update a UI or persist as work progresses.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Iterator
from urllib.parse import quote_plus

import feedparser
import httpx
from dateutil import parser as dateparser

from . import config as cfg
from .models import Item
from . import cache as db
from .sources import (
    ARXIV_CATEGORIES,
    HN_QUERIES,
    RSS_FEEDS,
    SUBREDDITS,
)

log = logging.getLogger("clankernewsdump")

UA = "clankernewsdump/0.2 (+https://github.com/brianziebart)"
HEADERS = {"User-Agent": UA}

# In-memory HTTP cache: url → {"etag": ..., "last_modified": ..., "content": bytes}
_http_cache: dict[str, dict] = {}


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


def _get_with_cache(url: str, timeout: float | None = None) -> httpx.Response:
    """HTTP GET with ETag/Last-Modified conditional request support."""
    timeout = timeout or cfg.get("timeout")
    headers = dict(HEADERS)
    cached = _http_cache.get(url)
    if cached:
        if cached.get("etag"):
            headers["If-None-Match"] = cached["etag"]
        if cached.get("last_modified"):
            headers["If-Modified-Since"] = cached["last_modified"]

    resp = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)

    if resp.status_code == 304 and cached:
        # Not modified — return a synthetic response with cached content
        resp._content = cached["content"]
    else:
        # Cache the response
        _http_cache[url] = {
            "etag": resp.headers.get("etag"),
            "last_modified": resp.headers.get("last-modified"),
            "content": resp.content,
        }
    return resp


def _fetch_with_retry(fetch_fn: Callable, label: str) -> list[Item]:
    """Wrap a fetch function with retry + backoff."""
    max_retries = cfg.get("max_retries")
    for attempt in range(max_retries + 1):
        try:
            return fetch_fn()
        except httpx.TimeoutException:
            log.warning("Timeout fetching %s (attempt %d/%d)", label, attempt + 1, max_retries + 1)
        except httpx.HTTPStatusError as e:
            log.warning("HTTP %d from %s (attempt %d/%d)", e.response.status_code, label, attempt + 1, max_retries + 1)
        except Exception as e:
            log.warning("Error fetching %s: %s (attempt %d/%d)", label, e, attempt + 1, max_retries + 1)
        if attempt < max_retries:
            time.sleep(1.5 ** attempt)
    log.error("All retries exhausted for %s", label)
    return []


# ---------- Per-source fetchers ----------


def _word_count(html: str) -> int:
    import re
    text = re.sub(r"<[^>]+>", " ", html)
    return len(text.split())


def fetch_one_rss(name: str, url: str, category: str, since: datetime) -> list[Item]:
    def _do():
        resp = _get_with_cache(url)
        feed = feedparser.parse(resp.content)
        out: list[Item] = []
        max_entries = cfg.get("max_entries_per_feed")
        min_words = cfg.get("min_words_blog")
        for entry in feed.entries[:max_entries]:
            published = None
            for field in ("published", "updated", "created"):
                if getattr(entry, field, None):
                    published = _parse_date(getattr(entry, field))
                    if published:
                        break
            if not published or published < since:
                continue
            snippet = getattr(entry, "summary", "") or getattr(entry, "description", "")
            if category in ("blog", "newsletter") and _word_count(snippet) < min_words:
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
    return _fetch_with_retry(_do, name)


def fetch_one_hn_query(query: str, since: datetime) -> list[Item]:
    def _do():
        min_score = cfg.get("min_score_hn")
        since_ts = int(since.timestamp())
        url = (
            "https://hn.algolia.com/api/v1/search"
            f"?query={quote_plus(query)}&tags=story&numericFilters=created_at_i>{since_ts},points>{min_score}"
            "&hitsPerPage=30"
        )
        data = httpx.get(url, headers=HEADERS, timeout=cfg.get("timeout")).json()
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
    return _fetch_with_retry(_do, f"HN:{query}")


def fetch_one_subreddit(sub: str, since: datetime) -> list[Item]:
    def _do():
        min_score = cfg.get("min_score_reddit")
        url = f"https://www.reddit.com/r/{sub}/top.json?t=week&limit=30"
        data = httpx.get(url, headers=HEADERS, timeout=cfg.get("timeout"), follow_redirects=True).json()
        out: list[Item] = []
        for child in data.get("data", {}).get("children", []):
            d = child.get("data", {})
            created = datetime.fromtimestamp(d.get("created_utc", 0), tz=timezone.utc)
            if created < since:
                continue
            score = d.get("score", 0)
            if score < min_score:
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
    return _fetch_with_retry(_do, f"r/{sub}")


def fetch_one_arxiv(cat: str, since: datetime) -> list[Item]:
    def _do():
        url = (
            "http://export.arxiv.org/api/query"
            f"?search_query=cat:{cat}&sortBy=submittedDate&sortOrder=descending&max_results=50"
        )
        resp = httpx.get(url, headers=HEADERS, timeout=cfg.get("timeout"))
        feed = feedparser.parse(resp.content)
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
    return _fetch_with_retry(_do, f"arXiv {cat}")


# ---------- Plan + iterator ----------


def build_plan(sources: Iterable[str] | None = None) -> list[tuple[str, Callable[[datetime], list[Item]]]]:
    """Return an ordered list of (label, fetch_fn) tasks. Each fetch_fn takes `since`."""
    sources = set(sources) if sources else {"rss", "hn", "reddit", "arxiv"}
    plan: list[tuple[str, Callable[[datetime], list[Item]]]] = []

    # Built-in + config file extras + DB custom sources
    extra_feeds = cfg.get("extra_feeds")
    all_rss = list(RSS_FEEDS)
    for ef in extra_feeds:
        if isinstance(ef, dict) and "name" in ef and "url" in ef:
            all_rss.append((ef["name"], ef["url"], ef.get("category", "blog")))
    all_rss.extend(db.get_custom_feeds())

    if "rss" in sources:
        for name, url, category in all_rss:
            plan.append((name, lambda since, n=name, u=url, c=category: fetch_one_rss(n, u, c, since)))
    if "hn" in sources:
        all_hn = list(HN_QUERIES) + list(cfg.get("extra_hn_queries")) + db.get_custom_hn_queries()
        for q in all_hn:
            plan.append((f"HN:{q}", lambda since, q=q: fetch_one_hn_query(q, since)))
    if "reddit" in sources:
        all_subs = list(SUBREDDITS) + list(cfg.get("extra_subreddits")) + db.get_custom_subreddits()
        for sub in all_subs:
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
        items = fn(since)
        yield label, i, total, items


def fetch_all(days: int, sources: Iterable[str] | None = None) -> list[Item]:
    """Blocking one-shot fetch (used by the flat dump mode)."""
    out: list[Item] = []
    for _label, _i, _total, items in fetch_incrementally(days, sources):
        out.extend(items)
    return out
