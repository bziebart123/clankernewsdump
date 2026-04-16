"""Interactive Textual TUI for browsing the news dump."""
from __future__ import annotations

import webbrowser
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

from rich.text import Text as RichText
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Footer, Header, Label, ListItem, ListView, Rule, Static

from . import cache as db
from .fetchers import fetch_incrementally
from .models import Item
from .summarize import summarize_item

CATEGORY_ORDER = ["subscribed", "blog", "newsletter", "lab", "podcast", "hn", "reddit", "arxiv", "news"]
CATEGORY_LABELS = {
    "subscribed": "* Subscribed",
    "blog": "Blogs",
    "newsletter": "Newsletters",
    "lab": "Lab Announcements",
    "podcast": "Podcasts",
    "hn": "Hacker News",
    "reddit": "Reddit",
    "arxiv": "arXiv Papers",
    "news": "News Outlets",
}
CATEGORY_COLORS = {
    "subscribed": "bold gold1",
    "blog": "cyan",
    "newsletter": "magenta",
    "lab": "green",
    "podcast": "yellow",
    "hn": "orange1",
    "reddit": "red",
    "arxiv": "blue",
    "news": "white",
}


def _esc(s: str) -> str:
    return s.replace("[", "\\[").replace("]", "\\]")


class CategoryItem(ListItem):
    def __init__(self, cat: str, count: int) -> None:
        self.cat = cat
        super().__init__()
        self._cat_color = CATEGORY_COLORS.get(cat, "white")
        self._cat_label = CATEGORY_LABELS.get(cat, cat)
        self._cat_count = count

    def compose(self) -> ComposeResult:
        yield Label(f"[{self._cat_color}]{self._cat_label}[/]  [dim]({self._cat_count})[/]")


class NewsItem(ListItem):
    """An item row with info label + Open button."""

    def __init__(self, item: Item, idx: int, is_subscribed: bool = False) -> None:
        self.item = item
        self.idx = idx
        self._is_sub = is_subscribed
        super().__init__()

    def compose(self) -> ComposeResult:
        it = self.item
        color = CATEGORY_COLORS.get(it.category, "white")
        date_str = it.published.strftime("%a %b %d")
        score = f" | {it.score}pts" if it.score else ""
        title = it.title.strip()
        if len(title) > 90:
            title = title[:87] + "..."
        star = "[gold1]*[/] " if self._is_sub else ""
        with Horizontal(classes="news-row"):
            yield Label(
                f"{star}[{color}]{_esc(title)}[/]\n"
                f"  [dim]{_esc(it.source)} | {date_str}{score}[/]",
                classes="news-label",
            )
            yield Button("Open", id=f"open-{self.idx}", classes="news-open-btn")


class ClankerApp(App):
    CSS = """
    Screen { layout: vertical; }

    #toolbar {
        height: auto;
        max-height: 5;
        padding: 1 2;
        border: solid $accent;
        layout: horizontal;
    }
    .toolbar-section {
        width: auto;
        height: auto;
        layout: horizontal;
        padding: 0 1;
    }
    .range-btn {
        min-width: 8;
        margin: 0 0 0 1;
    }
    .range-btn-active {
        min-width: 8;
        margin: 0 0 0 1;
    }
    #btn-rescrape {
        min-width: 14;
        margin: 0 0 0 2;
    }
    #scrape-indicator {
        width: 1fr;
        content-align: right middle;
        padding: 0 1;
    }

    #main { height: 1fr; }
    #sidebar {
        width: 28;
        border: solid $accent;
    }
    #middle {
        width: 1fr;
        border: solid $accent;
    }

    .news-row {
        width: 100%;
        height: auto;
        layout: horizontal;
    }
    .news-label {
        width: 1fr;
    }
    .news-open-btn {
        width: auto;
        min-width: 8;
        margin: 0 0 0 1;
    }

    #preview {
        height: 14;
        border: solid $accent;
        padding: 1 2;
    }
    #preview-inner { height: auto; }
    .preview-label {
        color: $accent;
        text-style: bold;
        margin-top: 1;
    }
    .preview-label-first {
        color: $accent;
        text-style: bold;
    }
    #preview-title-val { text-style: bold; }
    #preview-meta-val { color: $text-muted; }
    #preview-summary-val { margin-top: 0; }

    #status-bar {
        height: 1;
        background: $accent;
        color: $text;
        padding: 0 2;
    }
    ListView { background: $surface; }
    ListItem { padding: 0 1; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("o", "open_link", "Open link"),
        Binding("f", "toggle_subscribe", "Follow/Unfollow"),
        Binding("tab", "focus_next", "Next pane"),
        Binding("j", "cursor_down", "Down"),
        Binding("k", "cursor_up", "Up"),
    ]

    def __init__(
        self,
        initial_items: list[Item],
        summaries: dict[str, str],
        days: int,
        sources: set[str] | None,
    ) -> None:
        super().__init__()
        self._initial_days = days
        self._active_range = days
        self._date_end: date = date.today()
        self._date_start: date = self._date_end - timedelta(days=days)
        self.fetch_sources = sources
        self.summaries = dict(summaries)
        self.subscriptions: set[str] = db.get_subscriptions()
        self.groups: dict[str, list[Item]] = defaultdict(list)
        self._all_items: dict[str, Item] = {}
        self._current_items_list: list[Item] = []  # indexed for Open button lookup
        self._active_category: str = ""
        self.current_item: Item | None = None
        self._fetch_done = False
        self._fetch_running = False
        self._summarize_done = False
        self._items_total = 0
        self._items_summarized = 0
        self._ingest_items(initial_items)

    # ---------- item management ----------

    def _ingest_items(self, items: list[Item]) -> None:
        for it in items:
            if not it.url or it.url in self._all_items:
                continue
            self._all_items[it.url] = it
        self._rebuild_groups()

    def _rebuild_groups(self) -> None:
        self.groups = defaultdict(list)
        for it in self._all_items.values():
            d = it.published.date() if hasattr(it.published, "date") else it.published
            if d < self._date_start or d > self._date_end:
                continue
            self.groups[it.category].append(it)
            if it.source in self.subscriptions:
                self.groups["subscribed"].append(it)
        for cat in self.groups:
            self.groups[cat].sort(key=lambda x: (x.score, x.published), reverse=True)

    def _all_visible_items(self) -> list[Item]:
        seen: set[str] = set()
        out: list[Item] = []
        for cat in CATEGORY_ORDER:
            if cat == "subscribed":
                continue
            for it in self.groups.get(cat, []):
                if it.url not in seen:
                    seen.add(it.url)
                    out.append(it)
        return out

    # ---------- compose ----------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="toolbar"):
            with Horizontal(classes="toolbar-section"):
                yield Label("[bold]Range:[/] ", classes="toolbar-label")
                yield Button("3 days", id="range-3", classes="range-btn")
                yield Button("7 days", id="range-7", classes="range-btn")
                yield Button("14 days", id="range-14", classes="range-btn")
                yield Button("30 days", id="range-30", classes="range-btn")
            yield Button("Re-scrape", id="btn-rescrape")
            yield Static("", id="scrape-indicator")
        with Horizontal(id="main"):
            with Vertical(id="sidebar"):
                yield Label("[bold]Categories[/]", id="sidebar-label")
                yield ListView(id="cat-list")
            with Vertical(id="middle"):
                yield Label("[bold]Items[/]  [dim]o = open link | f = follow source[/]", id="items-label")
                yield ListView(id="item-list")
        with VerticalScroll(id="preview"):
            with Vertical(id="preview-inner"):
                yield Static("TITLE", classes="preview-label-first")
                yield Static("Select an item to preview.", id="preview-title-val")
                yield Static("SOURCE / DATE", classes="preview-label")
                yield Static("", id="preview-meta-val")
                yield Rule()
                yield Static("SUMMARY", classes="preview-label")
                yield Static("", id="preview-summary-val")
        yield Static("Loading...", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "CLANKERNEWSDUMP"
        self._highlight_active_range()
        self._refresh_scrape_indicator()
        self._refresh_categories()
        self._update_status()
        self._kick_off_fetch()

    # ---------- toolbar ----------

    def _set_date_range(self, days: int) -> None:
        self._active_range = days
        self._date_end = date.today()
        self._date_start = self._date_end - timedelta(days=days)
        # reload from DB for new range
        cached = db.load_items_in_range(self._date_start, self._date_end)
        for it in cached:
            if it.url not in self._all_items:
                self._all_items[it.url] = it
        self._rebuild_groups()
        self._highlight_active_range()
        self._refresh_scrape_indicator()
        self._refresh_categories()
        if self._active_category:
            self._refresh_item_list()
        self._update_sub_title()

    def _highlight_active_range(self) -> None:
        for days in (3, 7, 14, 30):
            btn = self.query_one(f"#range-{days}", Button)
            if days == self._active_range:
                btn.variant = "primary"
            else:
                btn.variant = "default"

    def _refresh_scrape_indicator(self) -> None:
        data_dates = db.dates_with_items(self._date_start, self._date_end)
        chars: list[str] = []
        d = self._date_start
        while d <= self._date_end:
            if d in data_dates:
                chars.append("[green]*[/]")
            elif d == date.today():
                chars.append("[yellow]~[/]")
            else:
                chars.append("[dim].[/]")
            d += timedelta(days=1)
        indicator = "".join(chars)
        has_count = len(data_dates)
        total_days = (self._date_end - self._date_start).days + 1
        self.query_one("#scrape-indicator", Static).update(
            f"{indicator}  {has_count}/{total_days}d  "
            f"[dim]([/][green]*[/][dim]=data [/][yellow]~[/][dim]=today [/][dim].=empty)[/]"
        )

    # ---------- background fetch ----------

    def _kick_off_fetch(self) -> None:
        if self._fetch_running:
            self.notify("Fetch already in progress.", severity="warning")
            return
        self._fetch_done = False
        self._fetch_running = True
        self._summarize_done = False
        self._update_status()
        self.run_worker(self._bg_fetch, thread=True, exclusive=False)

    def _bg_fetch(self) -> None:
        new_total = 0
        days = (self._date_end - self._date_start).days
        for label, i, total, items in fetch_incrementally(days, self.fetch_sources):
            status = f"Fetching: {_esc(label)} ({i}/{total})"
            self.call_from_thread(self._update_status_text, status)
            if items:
                inserted = db.upsert_items(items)
                new_total += inserted
                self.call_from_thread(self._merge_items, items)
        self._fetch_done = True
        self._fetch_running = False
        db.log_scrape(date.today(), new_total)
        self.call_from_thread(self._refresh_scrape_indicator)
        self.call_from_thread(self._update_status)
        self.call_from_thread(self.notify, f"Fetch complete. {new_total} new items.")
        self.call_from_thread(self._start_auto_summarize)

    def _start_auto_summarize(self) -> None:
        self.run_worker(self._bg_summarize_all, thread=True, exclusive=False)

    def _bg_summarize_all(self) -> None:
        all_items = self.call_from_thread(self._all_visible_items)
        unsummarized = [it for it in all_items if it.url not in self.summaries]
        self._items_total = len(all_items)
        self._items_summarized = len(all_items) - len(unsummarized)
        self.call_from_thread(self._update_status)

        with ThreadPoolExecutor(max_workers=4) as ex:
            futures = {ex.submit(summarize_item, it): it for it in unsummarized}
            for fut in as_completed(futures):
                it = futures[fut]
                try:
                    summary = fut.result()
                except Exception as e:
                    summary = f"[failed: {e}]"
                self.summaries[it.url] = summary
                self._items_summarized += 1
                self.call_from_thread(self._update_status)
                self.call_from_thread(self._refresh_preview_if_current, it, summary)

        self._summarize_done = True
        self.call_from_thread(self._update_status)
        self.call_from_thread(self.notify, "All summaries complete.")

    def _merge_items(self, items: list[Item]) -> None:
        had = len(self._all_items)
        self._ingest_items(items)
        if len(self._all_items) > had:
            self._refresh_categories()
            if self._active_category:
                self._refresh_item_list()
            self._update_sub_title()

    # ---------- UI refresh ----------

    def _update_sub_title(self) -> None:
        visible = sum(len(v) for k, v in self.groups.items() if k != "subscribed")
        self.sub_title = f"{visible} items"

    def _refresh_categories(self) -> None:
        cat_list = self.query_one("#cat-list", ListView)
        old_cat = self._active_category
        cat_list.clear()
        first_cat = ""
        for cat in CATEGORY_ORDER:
            items = self.groups.get(cat, [])
            if items:
                cat_list.append(CategoryItem(cat, len(items)))
                if not first_cat:
                    first_cat = cat
        if not old_cat and first_cat:
            self._active_category = first_cat
            self._load_category(first_cat)
        elif old_cat:
            self._active_category = old_cat
        self._update_sub_title()

    def _load_category(self, cat: str) -> None:
        self._active_category = cat
        self._refresh_item_list()

    def _refresh_item_list(self) -> None:
        self._current_items_list = list(self.groups.get(self._active_category, []))
        item_list = self.query_one("#item-list", ListView)
        item_list.clear()
        for idx, it in enumerate(self._current_items_list):
            item_list.append(
                NewsItem(it, idx=idx, is_subscribed=(it.source in self.subscriptions))
            )
        if self._current_items_list:
            item_list.index = 0
            self._show_item(self._current_items_list[0])
        else:
            self._clear_preview()

    def _clear_preview(self) -> None:
        self.query_one("#preview-title-val", Static).update("No items in this category.")
        self.query_one("#preview-meta-val", Static).update("")
        self.query_one("#preview-summary-val", Static).update("")

    def _show_item(self, item: Item) -> None:
        self.current_item = item
        date_str = item.published.strftime("%A %b %d, %Y")
        score = f"  |  Score: {item.score}" if item.score else ""
        sub_tag = " (subscribed)" if item.source in self.subscriptions else ""

        self.query_one("#preview-title-val", Static).update(RichText(item.title, style="bold"))
        self.query_one("#preview-meta-val", Static).update(
            RichText(f"{item.source}{sub_tag}  |  {date_str}{score}", style="dim")
        )
        summary = self.summaries.get(item.url, "")
        if summary:
            self.query_one("#preview-summary-val", Static).update(RichText(summary))
        else:
            self.query_one("#preview-summary-val", Static).update(
                "[dim italic]Summarizing in background...[/]"
            )

    def _refresh_preview_if_current(self, item: Item, summary: str) -> None:
        if self.current_item and self.current_item.url == item.url:
            self.query_one("#preview-summary-val", Static).update(RichText(summary))

    def _update_status_text(self, text: str) -> None:
        bar = self.query_one("#status-bar", Static)
        parts = [text]
        if self._items_total:
            parts.append(f"Summaries: {self._items_summarized}/{self._items_total}")
        bar.update("  |  ".join(parts))

    def _update_status(self) -> None:
        parts = []
        if self._fetch_running and not self._fetch_done:
            parts.append("[yellow]Fetching...[/]")
        elif self._fetch_done:
            parts.append("[green]Fetch: done[/]")
        else:
            parts.append("[dim]Idle[/]")
        if self._items_total:
            if self._summarize_done:
                parts.append(f"[green]Summaries: {self._items_summarized}/{self._items_total}[/]")
            else:
                parts.append(f"[yellow]Summaries: {self._items_summarized}/{self._items_total}[/]")
        visible = sum(len(v) for k, v in self.groups.items() if k != "subscribed")
        parts.append(f"Items: {visible}")
        subs = len(self.subscriptions)
        if subs:
            parts.append(f"[gold1]Subscriptions: {subs}[/]")
        self.query_one("#status-bar", Static).update("  |  ".join(parts))

    # ---------- event handlers ----------

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item is None:
            return
        if isinstance(event.item, CategoryItem):
            self._load_category(event.item.cat)
        elif isinstance(event.item, NewsItem):
            self._show_item(event.item.item)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, CategoryItem):
            self._load_category(event.item.cat)
            self.query_one("#item-list", ListView).focus()
        elif isinstance(event.item, NewsItem):
            # selecting an item just updates preview, does NOT open browser
            self._show_item(event.item.item)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        # Range buttons
        if btn_id.startswith("range-"):
            try:
                days = int(btn_id.split("-")[1])
                self._set_date_range(days)
                self.notify(f"Showing last {days} days")
            except (ValueError, IndexError):
                pass
            return
        # Re-scrape
        if btn_id == "btn-rescrape":
            self._kick_off_fetch()
            return
        # Open buttons on item rows
        if btn_id.startswith("open-"):
            try:
                idx = int(btn_id.split("-")[1])
                if 0 <= idx < len(self._current_items_list):
                    item = self._current_items_list[idx]
                    webbrowser.open(item.url)
                    self.notify(f"Opened: {item.title[:60]}")
            except (ValueError, IndexError):
                pass
            return

    def action_open_link(self) -> None:
        if self.current_item and self.current_item.url:
            webbrowser.open(self.current_item.url)
            self.notify(f"Opened: {self.current_item.title[:60]}")

    def action_toggle_subscribe(self) -> None:
        if not self.current_item:
            return
        source = self.current_item.source
        is_now = db.toggle_subscription(source)
        self.subscriptions = db.get_subscriptions()
        if is_now:
            self.notify(f"Subscribed to: {source}")
        else:
            self.notify(f"Unsubscribed from: {source}")
        self._rebuild_groups()
        self._refresh_categories()
        self._refresh_item_list()
        self._show_item(self.current_item)
        self._update_status()

    def action_cursor_down(self) -> None:
        focused = self.focused
        if isinstance(focused, ListView):
            focused.action_cursor_down()

    def action_cursor_up(self) -> None:
        focused = self.focused
        if isinstance(focused, ListView):
            focused.action_cursor_up()


def run_tui(
    initial_items: list[Item],
    summaries: dict[str, str],
    days: int,
    sources: set[str] | None,
) -> None:
    app = ClankerApp(initial_items, summaries, days, sources)
    app.run()
