"""Generate a self-contained HTML feed page.

Produces a single .html file with inline CSS + JS. No server needed.
Features: search/filter, category tabs, bookmarks (localStorage),
read/unread tracking, dark theme, responsive layout.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from . import cache as db
from . import config as cfg
from .constants import CATEGORY_COLORS, CATEGORY_LABELS, CATEGORY_ORDER
from .models import Item


def _group(items: list[Item], subscriptions: set[str]) -> dict[str, list[Item]]:
    groups: defaultdict[str, list[Item]] = defaultdict(list)
    seen: set[str] = set()
    for it in items:
        if not it.url or it.url in seen:
            continue
        seen.add(it.url)
        groups[it.category].append(it)
        if it.source in subscriptions:
            groups["subscribed"].append(it)
    for cat in groups:
        groups[cat].sort(key=lambda x: (x.score, x.published), reverse=True)
    return dict(groups)


def _items_to_json_records(items: list[Item], summaries: dict[str, str],
                           bookmarks: set[str], read_urls: set[str]) -> list[dict]:
    records = []
    for it in items:
        records.append({
            "t": it.title,
            "u": it.url,
            "s": it.source,
            "c": it.category,
            "d": it.published.strftime("%Y-%m-%dT%H:%M:%S"),
            "ds": it.published.strftime("%a %b %d"),
            "sc": it.score,
            "sm": summaries.get(it.url, ""),
            "b": it.url in bookmarks,
            "r": it.url in read_urls,
        })
    return records


def generate_html(
    items: list[Item],
    summaries: dict[str, str],
    days: int,
) -> str:
    subscriptions = db.get_subscriptions()
    bookmarks = db.get_bookmarks()
    read_urls = db.get_read_urls()
    custom_sources = db.get_all_custom_sources()
    groups = _group(items, subscriptions)

    # Build category tab data
    cat_tabs = []
    total_count = 0
    for cat in CATEGORY_ORDER:
        cat_items = groups.get(cat, [])
        if cat_items:
            cat_tabs.append({
                "id": cat,
                "label": CATEGORY_LABELS.get(cat, cat),
                "count": len(cat_items),
                "color": CATEGORY_COLORS.get(cat, "#888"),
            })
            if cat != "subscribed":
                total_count += len(cat_items)

    # Dedup items for JSON payload
    seen: set[str] = set()
    all_items: list[Item] = []
    for cat in CATEGORY_ORDER:
        for it in groups.get(cat, []):
            if it.url not in seen:
                seen.add(it.url)
                all_items.append(it)

    def _safe_json(obj: object) -> str:
        """Serialize to JSON safe for embedding in <script> tags."""
        s = json.dumps(obj, ensure_ascii=False)
        # Prevent </script> breakout and HTML comment injection
        return s.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")

    items_json = _safe_json(_items_to_json_records(all_items, summaries, bookmarks, read_urls))
    cats_json = _safe_json(cat_tabs)
    custom_sources_json = _safe_json(custom_sources)
    gen_date = date.today().strftime("%B %d, %Y")

    return f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>clankernewsdump</title>
<style>
:root {{
  --bg: #0d1117; --bg2: #151b23; --bg3: #212830; --bg-hover: #262c36;
  --card: #161b22; --card-border: #2a3040; --card-hover: #1c2333;
  --text: #e6edf3; --text2: #9198a1; --text3: #656d76;
  --border: #30363d; --accent: #58a6ff; --accent2: #388bfd;
  --gold: #f0c040; --red: #f85149; --green: #3fb950;
  --summary-bg: #1c2333; --summary-border: #263045;
}}
[data-theme="light"] {{
  --bg: #f5f5f5; --bg2: #ffffff; --bg3: #eaeef2; --bg-hover: #dde2e8;
  --card: #ffffff; --card-border: #d8dee4; --card-hover: #f6f8fa;
  --text: #1f2328; --text2: #59636e; --text3: #8b949e;
  --border: #d0d7de; --accent: #0969da; --accent2: #0550ae;
  --gold: #bf8700; --red: #cf222e; --green: #1a7f37;
  --summary-bg: #f6f8fa; --summary-border: #e1e4e8;
}}
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  background: var(--bg); color: var(--text); line-height: 1.5;
}}
a {{ color: var(--accent); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}

/* Header */
.header {{
  background: var(--bg2); border-bottom: 1px solid var(--border);
  padding: 12px 24px; display: flex; align-items: center; gap: 12px;
  flex-wrap: wrap; position: sticky; top: 0; z-index: 100;
}}
.header h1 {{ font-size: 18px; white-space: nowrap; letter-spacing: -0.3px; }}
.header h1 span {{ color: var(--text3); font-weight: 400; font-size: 13px; margin-left: 8px; }}
.search-box {{
  flex: 1; min-width: 180px; max-width: 420px; position: relative;
}}
.search-box input {{
  width: 100%; padding: 7px 12px 7px 34px; border-radius: 6px;
  border: 1px solid var(--border); background: var(--bg3); color: var(--text);
  font-size: 13px; outline: none;
}}
.search-box input:focus {{ border-color: var(--accent); box-shadow: 0 0 0 3px rgba(88,166,255,0.12); }}
.search-box svg {{
  position: absolute; left: 10px; top: 50%; transform: translateY(-50%);
  width: 14px; height: 14px; fill: var(--text3);
}}
.header-right {{ display: flex; gap: 6px; align-items: center; margin-left: auto; }}
.hdr-btn {{
  background: var(--bg3); border: 1px solid var(--border); color: var(--text2);
  padding: 5px 10px; border-radius: 6px; cursor: pointer; font-size: 12px;
  white-space: nowrap; transition: all .12s;
}}
.hdr-btn:hover {{ background: var(--bg-hover); color: var(--text); }}
.hdr-btn.active {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
.hdr-btn.gear {{ font-size: 16px; padding: 4px 8px; }}

/* Category tabs */
.tab-bar {{
  display: flex; align-items: center; gap: 2px; padding: 8px 24px 0; background: var(--bg2);
  border-bottom: 1px solid var(--border); overflow-x: auto;
}}
.tab {{
  padding: 7px 14px; border-radius: 6px 6px 0 0; cursor: pointer;
  font-size: 12px; font-weight: 600; white-space: nowrap; transition: all .12s;
  border: 1px solid transparent; border-bottom: none; color: var(--text3);
  background: transparent; display: flex; align-items: center; gap: 5px;
  user-select: none;
}}
.tab:hover {{ background: var(--bg3); color: var(--text2); }}
.tab.active {{ background: var(--bg); color: var(--text); border-color: var(--border); position: relative; }}
.tab.active::after {{
  content: ''; position: absolute; bottom: -1px; left: 0; right: 0;
  height: 1px; background: var(--bg);
}}
.tab .dot {{ width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }}
.tab .cnt {{ font-weight: 400; color: var(--text3); font-size: 11px; }}
.tab-spacer {{ flex: 1; }}
.sort-toggle {{
  font-size: 12px; color: var(--text3); cursor: pointer; padding: 7px 10px;
  white-space: nowrap; user-select: none; margin-left: auto;
}}
.sort-toggle:hover {{ color: var(--text2); }}
.sort-toggle strong {{ color: var(--text2); }}

/* Feed */
.feed {{ max-width: 920px; margin: 0 auto; padding: 12px 24px 40px; }}
.feed-status {{
  font-size: 12px; color: var(--text3); padding: 8px 0 4px;
  display: flex; justify-content: space-between; align-items: center;
}}
.feed-status .kbd {{ font-size: 10px; color: var(--text3); opacity: 0.7; }}
.feed-status .kbd kbd {{
  background: var(--bg3); border: 1px solid var(--border); border-radius: 3px;
  padding: 1px 5px; font-family: inherit; font-size: 10px;
}}

/* Item cards */
.item {{
  padding: 14px 16px; margin-bottom: 6px; border-radius: 8px;
  border: 1px solid var(--card-border); background: var(--card);
  transition: all .12s; position: relative;
}}
.item:hover {{ background: var(--card-hover); border-color: var(--text3); }}
.item.focused {{ border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }}
.item.read {{ opacity: 0.55; }}
.item.read:hover, .item.read.focused {{ opacity: 0.8; }}

.item-row {{ display: flex; align-items: flex-start; gap: 10px; }}
.item-body {{ flex: 1; min-width: 0; }}

.item-title {{
  font-size: 14px; font-weight: 600; line-height: 1.4; margin-bottom: 5px;
}}
.item-title a {{ color: var(--text); transition: color .1s; }}
.item-title a:hover {{ color: var(--accent); text-decoration: none; }}

.item-meta {{
  display: flex; gap: 6px; align-items: center; flex-wrap: wrap;
  font-size: 11px; color: var(--text3); line-height: 1;
}}
.item-meta .sep {{ color: var(--border); }}
.badge {{
  display: inline-block; padding: 2px 8px; border-radius: 10px;
  font-size: 10px; font-weight: 600; letter-spacing: 0.3px;
  text-transform: uppercase; border: 1px solid;
}}
.score-badge {{
  color: var(--gold); font-weight: 700; font-size: 11px;
}}
.time-ago {{ color: var(--text3); }}
.source-name {{ color: var(--text2); }}

/* Summary */
.item-summary {{
  margin-top: 8px; padding: 8px 10px; border-radius: 6px;
  background: var(--summary-bg); border-left: 3px solid var(--summary-border);
  font-size: 12.5px; color: var(--text2); line-height: 1.55;
}}
.summaries-hidden .item-summary {{ display: none; }}

/* Action buttons */
.item-actions {{
  display: flex; flex-direction: column; gap: 2px; flex-shrink: 0;
  padding-top: 2px;
}}
.act {{
  width: 30px; height: 28px; display: flex; align-items: center; justify-content: center;
  background: var(--bg3); border: 1px solid var(--card-border); border-radius: 5px;
  cursor: pointer; font-size: 15px; color: var(--text3); transition: all .12s;
}}
.act:hover {{ border-color: var(--text3); color: var(--text2); background: var(--bg-hover); }}
.act.on-bookmark {{ background: rgba(240,192,64,0.12); color: var(--gold); border-color: rgba(240,192,64,0.3); }}
.act.on-read {{ background: rgba(63,185,80,0.10); color: var(--green); border-color: rgba(63,185,80,0.25); }}

/* Empty state */
.empty {{ text-align: center; padding: 80px 20px; color: var(--text3); }}
.empty h2 {{ font-size: 16px; margin-bottom: 6px; color: var(--text2); }}

/* Footer */
.footer {{ text-align: center; padding: 24px; color: var(--text3); font-size: 11px; }}

/* Settings modal */
.modal-overlay {{
  display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0,0,0,0.6); z-index: 200; align-items: center; justify-content: center;
}}
.modal-overlay.open {{ display: flex; }}
.modal {{
  background: var(--bg2); border: 1px solid var(--border); border-radius: 12px;
  width: 90%; max-width: 600px; max-height: 85vh; overflow-y: auto; padding: 24px;
}}
.modal h2 {{ font-size: 16px; margin-bottom: 14px; }}
.modal h3 {{ font-size: 12px; color: var(--text3); margin: 18px 0 6px; text-transform: uppercase; letter-spacing: 0.5px; }}
.modal-close {{
  float: right; background: none; border: none; color: var(--text3);
  font-size: 20px; cursor: pointer; padding: 0 4px; line-height: 1;
}}
.modal-close:hover {{ color: var(--text); }}
.sf {{ display: flex; gap: 6px; margin-bottom: 6px; flex-wrap: wrap; }}
.sf input, .sf select {{
  padding: 5px 8px; border-radius: 5px; border: 1px solid var(--border);
  background: var(--bg3); color: var(--text); font-size: 12px; outline: none;
}}
.sf input:focus, .sf select:focus {{ border-color: var(--accent); }}
.sf input[type="text"] {{ flex: 1; min-width: 100px; }}
.sf button {{
  padding: 5px 12px; border-radius: 5px; border: 1px solid var(--accent);
  background: var(--accent); color: #fff; font-size: 12px; cursor: pointer;
}}
.sf button:hover {{ background: var(--accent2); }}
.src-list {{ list-style: none; }}
.src-list li {{
  display: flex; align-items: center; gap: 6px; padding: 5px 0;
  border-bottom: 1px solid var(--border); font-size: 12px;
}}
.src-list li:last-child {{ border-bottom: none; }}
.src-list .sn {{ font-weight: 500; }}
.src-list .sm {{ color: var(--text3); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.src-list .sr {{
  background: none; border: none; color: var(--red); cursor: pointer;
  font-size: 14px; padding: 2px 4px; opacity: 0.6;
}}
.src-list .sr:hover {{ opacity: 1; }}
.hint {{ font-size: 11px; color: var(--text3); margin: 3px 0 10px; }}
.cmd-box {{
  background: var(--bg3); border: 1px solid var(--border); border-radius: 5px;
  padding: 6px 10px; font-family: monospace; font-size: 11px; color: var(--text2);
  margin: 6px 0; word-break: break-all; cursor: pointer; position: relative;
}}
.cmd-box:hover {{ border-color: var(--accent); }}
.cmd-box::after {{ content: 'click to copy'; position: absolute; right: 6px; top: 6px; font-size: 9px; color: var(--text3); font-family: sans-serif; }}

/* Scrollbar */
::-webkit-scrollbar {{ width: 7px; }}
::-webkit-scrollbar-track {{ background: transparent; }}
::-webkit-scrollbar-thumb {{ background: var(--bg3); border-radius: 4px; }}
::-webkit-scrollbar-thumb:hover {{ background: var(--border); }}

@media (max-width: 640px) {{
  .header {{ padding: 10px 14px; gap: 8px; }}
  .tab-bar {{ padding: 6px 14px 0; }}
  .feed {{ padding: 10px 14px; }}
  .search-box {{ min-width: 140px; }}
  .header h1 span {{ display: none; }}
  .modal {{ width: 96%; padding: 16px; }}
  .feed-status .kbd {{ display: none; }}
}}
</style>
</head>
<body>

<div class="header">
  <h1>clankernewsdump<span>{total_count} items &middot; {days}d &middot; {gen_date}</span></h1>
  <div class="search-box">
    <svg viewBox="0 0 16 16"><path d="M10.68 11.74a6 6 0 1 1 1.06-1.06l3.04 3.04a.75.75 0 1 1-1.06 1.06l-3.04-3.04zM11.5 7a4.5 4.5 0 1 0-9 0 4.5 4.5 0 0 0 9 0z"/></svg>
    <input type="text" id="search" placeholder="Search titles, sources... ( / )" autocomplete="off">
  </div>
  <div class="header-right">
    <button class="hdr-btn" id="btn-unread">Unread</button>
    <button class="hdr-btn" id="btn-bookmarks">Bookmarks</button>
    <button class="hdr-btn" id="btn-summaries">Summaries</button>
    <button class="hdr-btn gear" id="btn-settings" title="Settings">&#9881;</button>
    <button class="hdr-btn" id="btn-theme">Light</button>
  </div>
</div>

<div class="tab-bar" id="tab-bar"></div>

<!-- Settings Modal -->
<div class="modal-overlay" id="settings-modal">
  <div class="modal">
    <button class="modal-close" id="modal-close">&times;</button>
    <h2>Settings</h2>
    <h3>Add RSS Feed</h3>
    <div class="sf" id="form-feed">
      <input type="text" id="feed-name" placeholder="Name">
      <input type="text" id="feed-url" placeholder="Feed URL">
      <select id="feed-cat"><option value="blog">Blog</option><option value="newsletter">Newsletter</option><option value="lab">Lab</option><option value="podcast">Podcast</option><option value="news">News</option></select>
      <button id="btn-add-feed">Add</button>
    </div>
    <h3>Add Subreddit</h3>
    <div class="sf"><input type="text" id="sub-name" placeholder="e.g. LangChain"><button id="btn-add-sub">Add</button></div>
    <h3>Add Hacker News Query</h3>
    <div class="sf"><input type="text" id="hn-query" placeholder="e.g. RAG"><button id="btn-add-hn">Add</button></div>
    <h3>Custom Sources</h3>
    <ul class="src-list" id="custom-source-list"></ul>
    <p class="hint" id="no-custom-msg">No custom sources yet.</p>
    <h3>How It Works</h3>
    <p class="hint">Adding a source generates a CLI command. Click to copy, paste in terminal, re-run <code>clankernewsdump</code>.</p>
    <div id="cmd-output"></div>
  </div>
</div>

<div class="feed" id="feed"></div>
<div class="footer">Generated by <strong>clankernewsdump</strong> on {gen_date}</div>

<script>
const ALL_ITEMS = {items_json};
const CATEGORIES = {cats_json};
const CUSTOM_SOURCES = {custom_sources_json};

// HTML escaping — applied when interpolating data into innerHTML
function esc(s) {{
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#039;');
}}
// Only allow http/https URLs in href attributes to prevent javascript: XSS
function safeHref(url) {{
  if (!url) return '';
  const u = String(url).trim();
  if (/^https?:\/\//i.test(u)) return esc(u);
  return '';
}}

// State
let activeCat = 'all';
let searchQuery = '';
let showUnreadOnly = false;
let showBookmarksOnly = false;
let showSummaries = true;
let sortBy = 'score'; // 'score' or 'date'
let focusedIdx = -1;
let bookmarks = new Set(ALL_ITEMS.filter(i => i.b).map(i => i.u));
let readItems = new Set(ALL_ITEMS.filter(i => i.r).map(i => i.u));

const STORAGE_KEY = 'clankernewsdump';
function loadState() {{
  try {{
    const s = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{{}}');
    if (s.bookmarks) bookmarks = new Set([...bookmarks, ...s.bookmarks]);
    if (s.read) readItems = new Set([...readItems, ...s.read]);
    if (s.showSummaries === false) showSummaries = false;
    if (s.sortBy) sortBy = s.sortBy;
  }} catch(e) {{}}
}}
function saveState() {{
  localStorage.setItem(STORAGE_KEY, JSON.stringify({{
    bookmarks: [...bookmarks],
    read: [...readItems],
    showSummaries,
    sortBy,
  }}));
}}
loadState();

// Relative time
function timeAgo(dateStr) {{
  const now = new Date();
  const d = new Date(dateStr);
  const diffMs = now - d;
  const mins = Math.floor(diffMs / 60000);
  if (mins < 60) return mins + 'm ago';
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return hrs + 'h ago';
  const days = Math.floor(hrs / 24);
  if (days === 1) return 'yesterday';
  if (days < 7) return days + 'd ago';
  return d.toLocaleDateString('en-US', {{ month: 'short', day: 'numeric' }});
}}

// Theme
function initTheme() {{
  const saved = localStorage.getItem('clankernewsdump-theme');
  if (saved) document.documentElement.setAttribute('data-theme', saved);
  updateThemeBtn();
}}
function toggleTheme() {{
  const cur = document.documentElement.getAttribute('data-theme');
  const next = cur === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('clankernewsdump-theme', next);
  updateThemeBtn();
}}
function updateThemeBtn() {{
  const t = document.documentElement.getAttribute('data-theme');
  document.getElementById('btn-theme').textContent = t === 'dark' ? 'Light' : 'Dark';
}}

// Tabs
function renderTabs() {{
  const el = document.getElementById('tab-bar');
  const allCount = ALL_ITEMS.length;
  let h = `<div class="tab ${{activeCat==='all'?'active':''}}" data-cat="all">All <span class="cnt">${{allCount}}</span></div>`;
  h += CATEGORIES.map(c =>
    `<div class="tab ${{c.id===activeCat?'active':''}}" data-cat="${{c.id}}">` +
    `<span class="dot" style="background:${{c.color}}"></span>${{c.label}} <span class="cnt">${{c.count}}</span></div>`
  ).join('');
  h += `<div class="tab-spacer"></div>`;
  h += `<div class="sort-toggle" id="sort-toggle">Sort: <strong>${{sortBy === 'score' ? 'Score' : 'Date'}}</strong></div>`;
  el.innerHTML = h;
  el.querySelectorAll('.tab').forEach(tab => {{
    tab.addEventListener('click', () => {{
      activeCat = tab.dataset.cat;
      showBookmarksOnly = false;
      document.getElementById('btn-bookmarks').classList.remove('active');
      focusedIdx = -1;
      renderTabs();
      renderFeed();
    }});
  }});
  document.getElementById('sort-toggle').addEventListener('click', () => {{
    sortBy = sortBy === 'score' ? 'date' : 'score';
    saveState();
    renderTabs();
    renderFeed();
  }});
}}

// Filter
function getVisibleItems() {{
  let items = ALL_ITEMS;
  if (showBookmarksOnly) {{
    items = items.filter(i => bookmarks.has(i.u));
  }} else if (activeCat !== 'all') {{
    items = items.filter(i => i.c === activeCat);
  }}
  if (showUnreadOnly) {{
    items = items.filter(i => !readItems.has(i.u));
  }}
  if (searchQuery) {{
    // Split query into words — all must match somewhere (title, source, or summary)
    const words = searchQuery.toLowerCase().split(/ +/).filter(w => w.length > 0);
    items = items.filter(i => {{
      const haystack = (i.t + ' ' + i.s + ' ' + i.sm).toLowerCase();
      return words.every(w => haystack.includes(w));
    }});
  }}
  // Sort
  if (sortBy === 'date') {{
    items = [...items].sort((a,b) => b.d.localeCompare(a.d));
  }} else {{
    items = [...items].sort((a,b) => (b.sc - a.sc) || b.d.localeCompare(a.d));
  }}
  return items;
}}

// Render
function renderFeed() {{
  const items = getVisibleItems();
  const el = document.getElementById('feed');
  const summaryClass = showSummaries ? '' : 'summaries-hidden';

  if (!items.length) {{
    el.innerHTML = '<div class="empty"><h2>No items found</h2><p>Try a different tab, or clear your search.</p></div>';
    return;
  }}

  const unreadCount = items.filter(i => !readItems.has(i.u)).length;
  let statusHtml = `<div class="feed-status"><span>${{items.length}} items${{unreadCount < items.length ? ' &middot; ' + unreadCount + ' unread' : ''}}</span>` +
    `<span class="kbd"><kbd>j</kbd><kbd>k</kbd> navigate &middot; <kbd>o</kbd> open &middot; <kbd>b</kbd> bookmark &middot; <kbd>/</kbd> search</span></div>`;

  el.innerHTML = statusHtml + `<div class="${{summaryClass}}" id="item-list">` + items.map((item, idx) => {{
    const isRead = readItems.has(item.u);
    const isBm = bookmarks.has(item.u);
    const cat = CATEGORIES.find(c => c.id === item.c);
    const color = cat ? cat.color : '#888';
    const label = cat ? cat.label : item.c;
    return `<div class="item ${{isRead?'read':''}} ${{idx===focusedIdx?'focused':''}}" data-idx="${{idx}}" data-url="${{esc(item.u)}}">` +
      `<div class="item-row">` +
        `<div class="item-body">` +
          `<div class="item-title"><a href="${{safeHref(item.u)}}" target="_blank" rel="noopener" data-url="${{esc(item.u)}}">${{esc(item.t)}}</a></div>` +
          `<div class="item-meta">` +
            `<span class="badge" style="color:${{color}};border-color:${{color}}">${{esc(label)}}</span>` +
            `<span class="source-name">${{esc(item.s)}}</span>` +
            `<span class="sep">&middot;</span>` +
            `<span class="time-ago">${{timeAgo(item.d)}}</span>` +
            (item.sc ? `<span class="sep">&middot;</span><span class="score-badge">${{item.sc.toLocaleString()}} pts</span>` : '') +
          `</div>` +
          (item.sm ? `<div class="item-summary">${{esc(item.sm)}}</div>` : '') +
        `</div>` +
        `<div class="item-actions">` +
          `<div class="act ${{isBm?'on-bookmark':''}}" data-action="bookmark" data-url="${{esc(item.u)}}" title="Bookmark">&#9733;</div>` +
          `<div class="act ${{isRead?'on-read':''}}" data-action="read" data-url="${{esc(item.u)}}" title="Mark read/unread">&#10003;</div>` +
        `</div>` +
      `</div>` +
    `</div>`;
  }}).join('') + `</div>`;
}}

// Events
document.getElementById('feed').addEventListener('click', (e) => {{
  const act = e.target.closest('[data-action]');
  if (act) {{
    e.preventDefault();
    const url = act.dataset.url;
    if (act.dataset.action === 'bookmark') {{
      if (bookmarks.has(url)) bookmarks.delete(url); else bookmarks.add(url);
    }} else if (act.dataset.action === 'read') {{
      if (readItems.has(url)) readItems.delete(url); else readItems.add(url);
    }}
    saveState(); renderFeed(); return;
  }}
  const link = e.target.closest('a[data-url]');
  if (link) {{
    readItems.add(link.dataset.url);
    saveState();
    setTimeout(renderFeed, 150);
  }}
  const item = e.target.closest('.item[data-idx]');
  if (item) {{
    focusedIdx = parseInt(item.dataset.idx);
    renderFeed();
  }}
}});

// Search
document.getElementById('search').addEventListener('input', (e) => {{
  searchQuery = e.target.value;
  focusedIdx = -1;
  renderFeed();
}});

// Keyboard nav
document.addEventListener('keydown', (e) => {{
  if (document.querySelector('.modal-overlay.open')) return;
  const inInput = document.activeElement.tagName === 'INPUT';
  if (e.key === '/' && !inInput) {{
    e.preventDefault();
    document.getElementById('search').focus();
    return;
  }}
  if (e.key === 'Escape') {{
    document.getElementById('search').blur();
    document.getElementById('search').value = '';
    searchQuery = '';
    focusedIdx = -1;
    renderFeed();
    return;
  }}
  if (inInput) return;
  const items = getVisibleItems();
  if (e.key === 'j' || e.key === 'ArrowDown') {{
    e.preventDefault();
    focusedIdx = Math.min(focusedIdx + 1, items.length - 1);
    renderFeed();
    const focused = document.querySelector('.item.focused');
    if (focused) focused.scrollIntoView({{ block: 'nearest', behavior: 'smooth' }});
  }}
  if (e.key === 'k' || e.key === 'ArrowUp') {{
    e.preventDefault();
    focusedIdx = Math.max(focusedIdx - 1, 0);
    renderFeed();
    const focused = document.querySelector('.item.focused');
    if (focused) focused.scrollIntoView({{ block: 'nearest', behavior: 'smooth' }});
  }}
  if (e.key === 'o' || e.key === 'Enter') {{
    if (focusedIdx >= 0 && focusedIdx < items.length) {{
      const item = items[focusedIdx];
      window.open(item.u, '_blank');
      readItems.add(item.u);
      saveState();
      renderFeed();
    }}
  }}
  if (e.key === 'b') {{
    if (focusedIdx >= 0 && focusedIdx < items.length) {{
      const url = items[focusedIdx].u;
      if (bookmarks.has(url)) bookmarks.delete(url); else bookmarks.add(url);
      saveState();
      renderFeed();
    }}
  }}
  if (e.key === 'r') {{
    if (focusedIdx >= 0 && focusedIdx < items.length) {{
      const url = items[focusedIdx].u;
      if (readItems.has(url)) readItems.delete(url); else readItems.add(url);
      saveState();
      renderFeed();
    }}
  }}
}});

// Header buttons
document.getElementById('btn-unread').addEventListener('click', () => {{
  showUnreadOnly = !showUnreadOnly;
  document.getElementById('btn-unread').classList.toggle('active');
  focusedIdx = -1;
  renderFeed();
}});
document.getElementById('btn-bookmarks').addEventListener('click', () => {{
  showBookmarksOnly = !showBookmarksOnly;
  document.getElementById('btn-bookmarks').classList.toggle('active');
  focusedIdx = -1;
  renderFeed();
}});
document.getElementById('btn-summaries').addEventListener('click', () => {{
  showSummaries = !showSummaries;
  document.getElementById('btn-summaries').classList.toggle('active');
  saveState();
  renderFeed();
}});
document.getElementById('btn-theme').addEventListener('click', toggleTheme);

// Settings
const modal = document.getElementById('settings-modal');
document.getElementById('btn-settings').addEventListener('click', () => {{
  modal.classList.add('open'); renderCustomSources();
}});
document.getElementById('modal-close').addEventListener('click', () => modal.classList.remove('open'));
modal.addEventListener('click', (e) => {{ if (e.target === modal) modal.classList.remove('open'); }});

function showCmd(cmd) {{
  const out = document.getElementById('cmd-output');
  const box = document.createElement('div');
  box.className = 'cmd-box'; box.textContent = cmd; box.title = 'Click to copy';
  box.addEventListener('click', () => {{
    navigator.clipboard.writeText(cmd).then(() => {{
      box.style.borderColor = 'var(--green)';
      setTimeout(() => box.style.borderColor = '', 1500);
    }});
  }});
  out.prepend(box);
}}
function renderCustomSources() {{
  const list = document.getElementById('custom-source-list');
  const msg = document.getElementById('no-custom-msg');
  list.innerHTML = '';
  if (!CUSTOM_SOURCES.length) {{ msg.style.display = ''; return; }}
  msg.style.display = 'none';
  CUSTOM_SOURCES.forEach(s => {{
    const li = document.createElement('li');
    const tl = s.type === 'rss' ? s.category : s.type === 'subreddit' ? 'reddit' : 'hn';
    li.innerHTML = `<span class="sn">${{esc(s.name)}}</span><span class="sm">${{esc(tl)}}${{s.type==='rss'?' — '+esc(s.url):''}}</span>` +
      `<button class="sr" data-name="${{esc(s.name)}}">&times;</button>`;
    list.appendChild(li);
  }});
  list.querySelectorAll('.sr').forEach(btn => {{
    btn.addEventListener('click', () => showCmd(`clankernewsdump remove-source "${{btn.dataset.name}}"`));
  }});
}}
// Sanitize input for display in CLI commands (strip shell metacharacters)
function shellSafe(s) {{
  return s.replace(/[`$\\!"';&|<>(){{}}]/g, '');
}}
document.getElementById('btn-add-feed').addEventListener('click', () => {{
  const n = document.getElementById('feed-name').value.trim();
  const u = document.getElementById('feed-url').value.trim();
  const c = document.getElementById('feed-cat').value;
  if (!n || !u) return;
  if (!/^https?:\/\//i.test(u)) {{ alert('Feed URL must start with http:// or https://'); return; }}
  showCmd(`clankernewsdump add-feed "${{shellSafe(n)}}" "${{shellSafe(u)}}" ${{c}}`);
  document.getElementById('feed-name').value = '';
  document.getElementById('feed-url').value = '';
}});
document.getElementById('btn-add-sub').addEventListener('click', () => {{
  const n = document.getElementById('sub-name').value.trim().replace('r/', '');
  if (!n) return;
  if (!/^[A-Za-z0-9_]+$/.test(n)) {{ alert('Subreddit name must be alphanumeric'); return; }}
  showCmd(`clankernewsdump add-subreddit ${{shellSafe(n)}}`);
  document.getElementById('sub-name').value = '';
}});
document.getElementById('btn-add-hn').addEventListener('click', () => {{
  const q = document.getElementById('hn-query').value.trim();
  if (!q) return;
  showCmd(`clankernewsdump add-hn "${{shellSafe(q)}}"`);
  document.getElementById('hn-query').value = '';
}});

// Init summaries button state
if (!showSummaries) document.getElementById('btn-summaries').classList.add('active');

initTheme();
renderTabs();
renderFeed();
</script>
</body>
</html>"""


def write_html(items: list[Item], summaries: dict[str, str], days: int) -> Path:
    """Generate the HTML file and return its path."""
    html_path = Path(cfg.get("html_path")).expanduser()
    html_path.parent.mkdir(parents=True, exist_ok=True)
    content = generate_html(items, summaries, days)
    html_path.write_text(content, encoding="utf-8")
    return html_path
