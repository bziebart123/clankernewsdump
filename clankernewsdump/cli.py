"""CLI entry point for clankernewsdump.

Default mode: fetch, summarize, generate HTML feed, open in browser.
Use --flat for terminal text dump.
Use export/digest/opml subcommands for other output formats.
"""
from __future__ import annotations

import argparse
import logging
import sys
import webbrowser
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.rule import Rule
from rich.text import Text

from . import cache as db
from . import config as cfg
from .constants import CATEGORY_LABELS, CATEGORY_ORDER, CATEGORY_RICH_STYLES, escape_markup
from .fetchers import fetch_all
from .models import Item
from .summarize import set_backend, summarize_item

log = logging.getLogger("clankernewsdump")


def group_and_sort(items: list[Item]) -> dict[str, list[Item]]:
    groups: dict[str, list[Item]] = defaultdict(list)
    seen_urls: set[str] = set()
    for it in items:
        if not it.url or it.url in seen_urls:
            continue
        seen_urls.add(it.url)
        groups[it.category].append(it)
    for cat in groups:
        groups[cat].sort(key=lambda x: (x.score, x.published), reverse=True)
    return groups


# ---------- Flat terminal output ----------


def render_flat(console: Console, groups: dict[str, list[Item]], summaries: dict[str, str]) -> None:
    total = sum(len(v) for v in groups.values())
    console.print()
    console.print(Text.from_markup(
        f"[bold white on blue] CLANKERNEWSDUMP [/]  [dim]{total} items[/]"
    ))
    for cat in CATEGORY_ORDER:
        items = groups.get(cat, [])
        if not items or cat == "subscribed":
            continue
        style = CATEGORY_RICH_STYLES.get(cat, "bold white")
        label = CATEGORY_LABELS.get(cat, cat)
        console.print()
        console.print(Rule(f"[{style}]{label}[/] [dim]({len(items)})[/]", style=style.split()[-1]))
        for it in items:
            date_str = it.published.strftime("%a %b %d")
            score_str = f" [dim]|{it.score}[/]" if it.score else ""
            console.print()
            console.print(Text.from_markup(
                f"[{style}][link={it.url}]> {escape_markup(it.title)}[/link][/]"
            ))
            console.print(Text.from_markup(
                f"  [dim]{escape_markup(it.source)} | {date_str}{score_str}[/]"
            ))
            summary = summaries.get(it.url, "")
            if summary:
                console.print(Text.from_markup(f"  [white]{escape_markup(summary)}[/]"))
            console.print(Text.from_markup(
                f"  [blue underline][link={it.url}]{escape_markup(it.url)}[/link][/]"
            ))


# ---------- Fetch + summarize helpers ----------


def _fetch_items(console: Console, days: int, sources: set[str] | None) -> list[Item]:
    with Progress(
        SpinnerColumn(), TextColumn("{task.description}"), console=console, transient=True
    ) as prog:
        task = prog.add_task(f"Fetching last {days} days of AI news...", total=None)
        items = fetch_all(days=days, sources=sources)
        prog.update(task, description=f"Fetched {len(items)} items")
    return items


def _summarize_items(console: Console, items: list[Item]) -> dict[str, str]:
    # Pre-load cached summaries in bulk
    urls = [it.url for it in items]
    summaries = db.get_all_summaries(urls)
    unsummarized = [it for it in items if it.url not in summaries]

    if not unsummarized:
        return summaries

    workers = cfg.get("summary_workers")
    with Progress(
        SpinnerColumn(), TextColumn("{task.description}"), console=console, transient=True
    ) as prog:
        task = prog.add_task(
            f"Summarizing {len(unsummarized)} items...", total=len(unsummarized)
        )
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(summarize_item, it): it for it in unsummarized}
            for fut in as_completed(futures):
                it = futures[fut]
                try:
                    summaries[it.url] = fut.result()
                except Exception as e:
                    summaries[it.url] = f"[failed: {e}]"
                prog.advance(task)
    return summaries


# ---------- Commands ----------


def cmd_default(args: argparse.Namespace) -> int:
    """Default: fetch, summarize, generate HTML, open in browser."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    console = Console(legacy_windows=False)
    sources = None if args.source == "all" else {args.source}
    days = args.days

    items = _fetch_items(console, days, sources)

    if args.min_score:
        items = [i for i in items if i.category not in ("hn", "reddit") or i.score >= args.min_score]

    db.upsert_items(items)

    # Also load any cached items we might have missed
    cached = db.load_recent_items(days)
    seen = {it.url for it in items}
    for it in cached:
        if it.url not in seen:
            items.append(it)
            seen.add(it.url)

    groups = group_and_sort(items)
    if args.limit:
        for cat in groups:
            groups[cat] = groups[cat][:args.limit]

    all_items = [it for cat in CATEGORY_ORDER for it in groups.get(cat, []) if cat != "subscribed"]

    # Always load cached summaries; only generate new ones if --no-summary isn't set
    urls = [it.url for it in all_items]
    summaries = db.get_all_summaries(urls)
    if not args.no_summary:
        summaries = _summarize_items(console, all_items)

    if args.flat:
        render_flat(console, groups, summaries)
        console.print()
        return 0

    # HTML mode (default)
    from .htmlgen import write_html
    html_path = write_html(all_items, summaries, days)
    console.print(f"[green]Feed written to:[/] {html_path}")

    if cfg.get("open_browser"):
        webbrowser.open(html_path.as_uri())
        console.print("[dim]Opened in browser.[/]")

    return 0


def cmd_export(args: argparse.Namespace) -> int:
    """Export items in various formats."""
    from .export import to_digest, to_json, to_markdown

    console = Console(legacy_windows=False)
    sources = None if args.source == "all" else {args.source}
    days = args.days
    items = _fetch_items(console, days, sources)
    db.upsert_items(items)

    cached = db.load_recent_items(days)
    seen = {it.url for it in items}
    for it in cached:
        if it.url not in seen:
            items.append(it)
            seen.add(it.url)

    summaries = _summarize_items(console, items) if not args.no_summary else {}

    if args.format == "json":
        print(to_json(items, summaries))
    elif args.format == "markdown":
        print(to_markdown(items, summaries, days))
    elif args.format == "digest":
        limit = args.limit or 5
        print(to_digest(items, summaries, days, limit=limit))
    return 0


def cmd_opml(args: argparse.Namespace) -> int:
    """OPML import/export."""
    from .opml import export_opml, import_opml

    if args.action == "export":
        path = Path(args.file or "clankernewsdump.opml")
        count = export_opml(path)
        print(f"Exported {count} feeds to {path}")
    elif args.action == "import":
        if not args.file:
            print("Error: --file required for import", file=sys.stderr)
            return 1
        feeds = import_opml(args.file)
        print(f"Found {len(feeds)} feeds in {args.file}:")
        for f in feeds:
            print(f"  {f['name']} ({f['category']}) -> {f['url']}")
        print()
        print("Add these to your config.toml under [sources] extra_feeds.")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize config file."""
    path = cfg.init_config()
    print(f"Config file: {path}")
    print("Default config.toml created. Edit it to customize.")
    return 0


def cmd_add_feed(args: argparse.Namespace) -> int:
    """Add a custom RSS feed."""
    added = db.add_custom_source(args.name, args.url, args.category, "rss")
    if added:
        print(f"Added feed: {args.name} ({args.category}) -> {args.url}")
    else:
        print(f"Feed already exists: {args.url}")
    return 0


def cmd_add_subreddit(args: argparse.Namespace) -> int:
    """Add a custom subreddit."""
    name = args.name.removeprefix("r/")
    url = f"https://www.reddit.com/r/{name}"
    added = db.add_custom_source(name, url, "reddit", "subreddit")
    if added:
        print(f"Added subreddit: r/{name}")
    else:
        print(f"Subreddit already exists: r/{name}")
    return 0


def cmd_add_hn(args: argparse.Namespace) -> int:
    """Add a custom HN search query."""
    url = f"hn:{args.query}"
    added = db.add_custom_source(args.query, url, "hn", "hn_query")
    if added:
        print(f"Added HN query: {args.query}")
    else:
        print(f"HN query already exists: {args.query}")
    return 0


def cmd_remove_source(args: argparse.Namespace) -> int:
    """Remove a custom source."""
    removed = db.remove_custom_source(args.name_or_url)
    if removed:
        print(f"Removed: {args.name_or_url}")
    else:
        print(f"Not found: {args.name_or_url}")
    return 0


def cmd_feeds(args: argparse.Namespace) -> int:
    """List all sources (built-in + custom)."""
    from .sources import RSS_FEEDS, SUBREDDITS, HN_QUERIES, ARXIV_CATEGORIES

    custom = db.get_all_custom_sources()

    print("Built-in sources:")
    print(f"  RSS feeds:    {len(RSS_FEEDS)}")
    print(f"  Subreddits:   {len(SUBREDDITS)}")
    print(f"  HN queries:   {len(HN_QUERIES)}")
    print(f"  arXiv cats:   {len(ARXIV_CATEGORIES)}")

    if custom:
        print(f"\nCustom sources ({len(custom)}):")
        for s in custom:
            if s["type"] == "rss":
                print(f"  [{s['category']}] {s['name']} -> {s['url']}")
            elif s["type"] == "subreddit":
                print(f"  [reddit] r/{s['name']}")
            elif s["type"] == "hn_query":
                print(f"  [hn] HN: {s['name']}")
    else:
        print("\nNo custom sources. Add some with:")
        print("  clankernewsdump add-feed \"Name\" \"https://example.com/feed.xml\" blog")
        print("  clankernewsdump add-subreddit LangChain")
        print("  clankernewsdump add-hn \"RAG\"")

    return 0


def cmd_bookmarks(args: argparse.Namespace) -> int:
    """List or export bookmarked items."""
    from .export import to_json, to_markdown

    items = db.get_bookmarked_items()
    if not items:
        print("No bookmarks saved.")
        return 0

    urls = [it.url for it in items]
    summaries = db.get_all_summaries(urls)

    fmt = getattr(args, "format", "text")
    if fmt == "json":
        print(to_json(items, summaries))
    elif fmt == "markdown":
        print(to_markdown(items, summaries, days=0))
    else:
        for it in items:
            print(f"  {it.title}")
            print(f"    {it.url}")
            s = summaries.get(it.url, "")
            if s:
                print(f"    {s}")
            print()
    return 0


# ---------- Main ----------


def main() -> int:
    p = argparse.ArgumentParser(
        prog="clankernewsdump",
        description="AI news aggregator. Fetches, summarizes, and opens a local HTML feed.",
    )
    # Shared flags
    p.add_argument("--days", type=int, default=None, help="Days back to fetch (default: 7)")
    p.add_argument(
        "--source", choices=["rss", "hn", "reddit", "arxiv", "all"], default="all",
        help="Limit to one source type",
    )
    p.add_argument("--no-summary", action="store_true", help="Skip AI summaries")
    p.add_argument(
        "--backend", choices=["cli", "api"], default=None,
        help="Summarizer: 'cli' = local claude (default), 'api' = ANTHROPIC_API_KEY",
    )
    p.add_argument("--limit", type=int, default=0, help="Max items per category")
    p.add_argument("--min-score", type=int, default=0, help="Min score for HN/Reddit")
    p.add_argument("--flat", action="store_true", help="Flat terminal dump instead of HTML")
    p.add_argument("--no-open", action="store_true", help="Generate HTML but don't open browser")
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")

    sub = p.add_subparsers(dest="command")

    # export subcommand
    exp = sub.add_parser("export", help="Export feed in various formats")
    exp.add_argument("--format", choices=["json", "markdown", "digest"], default="markdown")

    # opml subcommand
    opm = sub.add_parser("opml", help="Import/export OPML feed lists")
    opm.add_argument("action", choices=["import", "export"])
    opm.add_argument("--file", type=str, help="OPML file path")

    # init subcommand
    sub.add_parser("init", help="Create default config.toml")

    # bookmarks subcommand
    bk = sub.add_parser("bookmarks", help="List bookmarked items")
    bk.add_argument("--format", choices=["text", "json", "markdown"], default="text")

    # add-feed subcommand
    af = sub.add_parser("add-feed", help="Add a custom RSS feed")
    af.add_argument("name", help="Display name for the feed")
    af.add_argument("url", help="RSS/Atom feed URL")
    af.add_argument("category", nargs="?", default="blog",
                    choices=["blog", "newsletter", "lab", "podcast", "news"],
                    help="Category (default: blog)")

    # add-subreddit subcommand
    asub = sub.add_parser("add-subreddit", help="Add a custom subreddit")
    asub.add_argument("name", help="Subreddit name (e.g. LangChain)")

    # add-hn subcommand
    ah = sub.add_parser("add-hn", help="Add a custom Hacker News search query")
    ah.add_argument("query", help="Search term (e.g. RAG)")

    # remove-source subcommand
    rs = sub.add_parser("remove-source", help="Remove a custom source by name or URL")
    rs.add_argument("name_or_url", help="Name or URL of the source to remove")

    # feeds subcommand
    sub.add_parser("feeds", help="List all sources (built-in + custom)")

    args = p.parse_args()

    # Logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Apply config overrides from CLI flags
    if args.days is not None:
        cfg.override("days", args.days)
    else:
        args.days = cfg.get("days")
    if args.backend:
        set_backend(args.backend)
    if args.no_open:
        cfg.override("open_browser", False)

    prune_days = cfg.get("cache_prune_days")
    db.prune_old_items(prune_days)

    # Route to subcommand
    if args.command == "export":
        return cmd_export(args)
    elif args.command == "opml":
        return cmd_opml(args)
    elif args.command == "init":
        return cmd_init(args)
    elif args.command == "bookmarks":
        return cmd_bookmarks(args)
    elif args.command == "add-feed":
        return cmd_add_feed(args)
    elif args.command == "add-subreddit":
        return cmd_add_subreddit(args)
    elif args.command == "add-hn":
        return cmd_add_hn(args)
    elif args.command == "remove-source":
        return cmd_remove_source(args)
    elif args.command == "feeds":
        return cmd_feeds(args)
    else:
        return cmd_default(args)


if __name__ == "__main__":
    raise SystemExit(main())
