# clankernewsdump

AI news aggregator for engineering teams. Pulls from 80+ sources (blogs, newsletters, labs, podcasts, HN, Reddit, arXiv, news outlets), generates Claude-powered 2-sentence summaries, and opens a local HTML feed in your browser.

No server. No account. Just run it.

## Quick start

```bash
git clone https://github.com/bziebart123/clankernewsdump.git
cd clankernewsdump
pip install -e .
clankernewsdump
```

This fetches the last 7 days of AI news, summarizes everything, and opens an HTML page in your browser.

### Requirements

- Python 3.11+
- [Claude Code](https://claude.ai/download) on your PATH (for summaries), **or** set `ANTHROPIC_API_KEY` and use `--backend api`

## Usage

```bash
# Default: fetch + summarize + open HTML feed
clankernewsdump

# Last 14 days, skip summaries
clankernewsdump --days 14 --no-summary

# Only Hacker News + Reddit, minimum 100 points
clankernewsdump --source hn --min-score 100

# Flat terminal dump (no browser)
clankernewsdump --flat

# Generate HTML but don't auto-open
clankernewsdump --no-open

# Use API instead of Claude CLI for summaries
clankernewsdump --backend api

# Verbose logging (see fetch errors, retries, etc.)
clankernewsdump -v
```

## Export

```bash
# Markdown digest
clankernewsdump export --format markdown

# JSON (all items + summaries)
clankernewsdump export --format json

# Curated digest (top 5 per category, good for Slack/email)
clankernewsdump export --format digest
```

## Bookmarks

Bookmark items in the HTML feed (star icon), then export them:

```bash
clankernewsdump bookmarks
clankernewsdump bookmarks --format markdown
clankernewsdump bookmarks --format json
```

## Managing Sources

Add custom feeds, subreddits, or HN queries from the CLI:

```bash
# Add an RSS feed
clankernewsdump add-feed "My Team Blog" "https://blog.example.com/feed.xml" blog

# Add a subreddit
clankernewsdump add-subreddit LangChain

# Add a Hacker News search term
clankernewsdump add-hn "RAG"

# List all sources (built-in + custom)
clankernewsdump feeds

# Remove a custom source
clankernewsdump remove-source "My Team Blog"
```

You can also manage sources from the Settings panel in the HTML feed (gear icon in the top right). It generates CLI commands you can copy-paste.

## OPML

Export your feed list for use in other RSS readers:

```bash
clankernewsdump opml export
clankernewsdump opml export --file my-feeds.opml
```

Import feeds from an OPML file (prints config entries to add):

```bash
clankernewsdump opml import --file feeds.opml
```

## Configuration

Create a config file:

```bash
clankernewsdump init
```

This writes `~/.clankernewsdump/config.toml` with commented defaults. Edit to customize:

```toml
[fetch]
days = 7
timeout = 20.0
max_retries = 2
min_score_hn = 50
min_score_reddit = 50

[summary]
summary_backend = "cli"       # or "api"
summary_workers = 4

[html]
open_browser = true

[sources]
extra_feeds = [
    {name = "My Team Blog", url = "https://blog.example.com/feed.xml", category = "blog"},
]
extra_subreddits = ["LangChain"]
extra_hn_queries = ["RAG"]
```

CLI flags always override config file values.

## Sources (80+)

| Category | Count | Examples |
|----------|-------|---------|
| Blogs | 24 | Simon Willison, Chip Huyen, Ethan Mollick, Gwern |
| Newsletters | 9 | The Batch, Latent Space, TLDR AI, Ben's Bites |
| Lab Announcements | 15 | Anthropic, OpenAI, DeepMind, Meta AI, HuggingFace |
| Podcasts | 11 | Dwarkesh, No Priors, Lex Fridman, Hard Fork |
| News Outlets | 7 | TechCrunch, The Verge, Ars Technica, Wired |
| Hacker News | 10 | Queries: LLM, Claude, GPT-5, AI agent, etc. |
| Reddit | 8 | LocalLLaMA, MachineLearning, OpenAI, ClaudeAI |
| arXiv | 3 | cs.AI, cs.LG, cs.CL |

## HTML feed features

- Category tabs with color-coded badges
- Full-text search across titles, sources, and summaries (press `/` to focus)
- Bookmark items (persisted to localStorage)
- Read/unread tracking (items dim after you click them)
- Unread-only and bookmarks-only filter buttons
- Settings panel (gear icon) for adding custom feeds, subreddits, and HN queries
- Light/dark theme toggle
- Responsive layout (works on mobile too)

## Data storage

Everything lives in `~/.clankernewsdump/`:

| File | Purpose |
|------|---------|
| `cache.db` | SQLite — items, summaries, bookmarks, read state |
| `feed.html` | Generated HTML feed (overwritten each run) |
| `config.toml` | Your configuration (created by `init`) |

Items older than 60 days are auto-pruned (configurable via `cache_prune_days`).

## Architecture

```
sources.py      → 80+ feed/API definitions
fetchers.py     → Per-source HTTP fetchers with retry + conditional caching
cache.py        → SQLite persistence layer
summarize.py    → Claude CLI or API summarization
htmlgen.py      → Self-contained HTML generator
export.py       → JSON / Markdown / digest formatters
opml.py         → OPML import/export
config.py       → TOML config loader
constants.py    → Shared category definitions
cli.py          → CLI entry point + argument routing
```
