"""CLI entry point for clankernewsdump.

Default mode: interactive Textual TUI with instant boot from DB cache.
Use --flat for the old linear terminal dump.
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.rule import Rule
from rich.text import Text

from . import cache as db
from .fetchers import fetch_all
from .models import Item
from .summarize import set_backend, summarize_item

CATEGORY_ORDER = ["subscribed", "blog", "newsletter", "lab", "podcast", "hn", "reddit", "arxiv", "news"]
CATEGORY_STYLE = {
    "blog": ("bold cyan", "BLOGS"),
    "newsletter": ("bold magenta", "NEWSLETTERS"),
    "lab": ("bold green", "LAB ANNOUNCEMENTS"),
    "podcast": ("bold yellow", "PODCASTS"),
    "hn": ("bold orange1", "HACKER NEWS"),
    "reddit": ("bold red", "REDDIT"),
    "arxiv": ("bold blue", "ARXIV PAPERS"),
    "news": ("bold white", "NEWS OUTLETS"),
}


def _escape(s: str) -> str:
    return s.replace("[", "\\[").replace("]", "\\]")


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


def render_flat(console: Console, groups: dict[str, list[Item]], summaries: dict[str, str]) -> None:
    total = sum(len(v) for v in groups.values())
    console.print()
    console.print(
        Panel.fit(
            Text.from_markup(
                f"[bold white on blue] CLANKERNEWSDUMP [/]  [dim]{total} items[/]"
            ),
            border_style="blue",
        )
    )
    for cat in CATEGORY_ORDER:
        items = groups.get(cat, [])
        if not items:
            continue
        style, label = CATEGORY_STYLE[cat]
        console.print()
        console.print(
            Rule(f"[{style}]{label}[/] [dim]({len(items)})[/]", style=style.split()[-1])
        )
        for it in items:
            date_str = it.published.strftime("%a %b %d")
            score_str = f" [dim]|{it.score}[/]" if it.score else ""
            console.print()
            console.print(
                Text.from_markup(
                    f"[{style}][link={it.url}]> {_escape(it.title)}[/link][/]"
                )
            )
            console.print(
                Text.from_markup(
                    f"  [dim]{_escape(it.source)} | {date_str}{score_str}[/]"
                )
            )
            summary = summaries.get(it.url, "")
            if summary:
                console.print(Text.from_markup(f"  [white]{_escape(summary)}[/]"))
            console.print(
                Text.from_markup(
                    f"  [blue underline][link={it.url}]{_escape(it.url)}[/link][/]"
                )
            )


def run_flat(args: argparse.Namespace) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    console = Console(legacy_windows=False)
    sources = None if args.source == "all" else {args.source}

    with Progress(
        SpinnerColumn(), TextColumn("{task.description}"), console=console, transient=True
    ) as prog:
        task = prog.add_task(f"Fetching last {args.days} days of AI news...", total=None)
        items = fetch_all(days=args.days, sources=sources)
        prog.update(task, description=f"Fetched {len(items)} items")

    if args.min_score:
        items = [i for i in items if i.category not in ("hn", "reddit") or i.score >= args.min_score]

    groups = group_and_sort(items)
    if args.limit:
        for cat in groups:
            groups[cat] = groups[cat][: args.limit]

    summaries: dict[str, str] = {}
    if not args.no_summary:
        all_items = [it for cat in CATEGORY_ORDER for it in groups.get(cat, [])]
        with Progress(
            SpinnerColumn(), TextColumn("{task.description}"), console=console, transient=True
        ) as prog:
            task = prog.add_task(
                f"Summarizing {len(all_items)} items...", total=len(all_items)
            )
            with ThreadPoolExecutor(max_workers=8) as ex:
                futures = {ex.submit(summarize_item, it): it for it in all_items}
                for fut in as_completed(futures):
                    it = futures[fut]
                    try:
                        summaries[it.url] = fut.result()
                    except Exception as e:
                        summaries[it.url] = f"[failed: {e}]"
                    prog.advance(task)

    render_flat(console, groups, summaries)
    console.print()
    return 0


def run_tui_mode(args: argparse.Namespace) -> int:
    from .tui import run_tui

    # 1. Instant boot from DB cache
    cached_items = db.load_recent_items(days=args.days)

    # 2. Pre-load cached summaries
    summaries: dict[str, str] = {}
    for it in cached_items:
        s = db.get_summary(it.url)
        if s:
            summaries[it.url] = s

    sources = None if args.source == "all" else {args.source}

    # 3. Launch TUI — fetches + summarizes in background
    run_tui(cached_items, summaries, args.days, sources)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        prog="clankernewsdump",
        description="Bleeding-edge AI news dump. Interactive TUI by default.",
    )
    p.add_argument("--days", type=int, default=7, help="Days back to fetch (default 7)")
    p.add_argument(
        "--source",
        choices=["rss", "hn", "reddit", "arxiv", "all"],
        default="all",
        help="Limit to one source type",
    )
    p.add_argument("--flat", action="store_true", help="Use flat terminal dump instead of TUI")
    p.add_argument("--no-summary", action="store_true", help="Skip summaries (flat mode only)")
    p.add_argument(
        "--backend",
        choices=["cli", "api"],
        default="cli",
        help="Summarizer: 'cli' = local claude (default), 'api' = ANTHROPIC_API_KEY",
    )
    p.add_argument("--limit", type=int, default=0, help="Max items per category (flat mode)")
    p.add_argument("--min-score", type=int, default=0, help="Min score for HN/Reddit")
    args = p.parse_args()

    set_backend(args.backend)
    db.prune_old_items()

    if args.flat:
        return run_flat(args)
    return run_tui_mode(args)


if __name__ == "__main__":
    raise SystemExit(main())
