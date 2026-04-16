"""Configuration file support.

Loads from ~/.clankernewsdump/config.toml if present, otherwise uses defaults.
CLI flags override config file values.
"""
from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".clankernewsdump"
CONFIG_PATH = CONFIG_DIR / "config.toml"

_DEFAULTS: dict[str, Any] = {
    # Fetching
    "days": 7,
    "timeout": 20.0,
    "max_retries": 2,
    "min_score_hn": 50,
    "min_score_reddit": 50,
    "min_words_blog": 40,
    "max_entries_per_feed": 40,
    "fetch_workers": 8,

    # Summarization
    "summary_model": "claude-haiku-4-5-20251001",
    "summary_max_tokens": 200,
    "summary_backend": "cli",
    "summary_workers": 4,
    "summary_prompt": (
        "You summarize AI/ML news items for a busy engineering manager. "
        "Write exactly 2 sentences: first what happened, second why it matters. "
        "Be concrete and specific. No hype words. No preamble. Output only the summary, nothing else."
    ),

    # Cache
    "cache_prune_days": 60,

    # HTML output
    "html_path": str(CONFIG_DIR / "feed.html"),
    "open_browser": True,

    # Extra RSS feeds (user-defined, appended to built-in sources)
    "extra_feeds": [],
    # Extra subreddits
    "extra_subreddits": [],
    # Extra HN queries
    "extra_hn_queries": [],
}

_config: dict[str, Any] | None = None


def _load() -> dict[str, Any]:
    global _config
    if _config is not None:
        return _config
    _config = dict(_DEFAULTS)
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            user = tomllib.load(f)
        # Flatten nested tables: [fetch] timeout = 30 → timeout = 30
        for section in ("fetch", "summary", "cache", "html", "sources"):
            if section in user:
                for k, v in user[section].items():
                    flat_key = f"{section}_{k}" if f"{section}_{k}" in _DEFAULTS else k
                    if flat_key in _DEFAULTS:
                        _config[flat_key] = v
                    elif k in _DEFAULTS:
                        _config[k] = v
        # Top-level overrides
        for k, v in user.items():
            if isinstance(v, dict):
                continue
            if k in _DEFAULTS:
                _config[k] = v
    return _config


def get(key: str) -> Any:
    return _load()[key]


def get_all() -> dict[str, Any]:
    return dict(_load())


def override(key: str, value: Any) -> None:
    """Override a config value (used by CLI flag processing)."""
    _load()[key] = value


def init_config() -> Path:
    """Write a default config.toml if one doesn't exist. Returns the path."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_PATH.exists():
        return CONFIG_PATH
    template = '''# clankernewsdump configuration
# Uncomment and edit values to override defaults.

# [fetch]
# days = 7                    # How many days back to fetch
# timeout = 20.0              # HTTP timeout per request (seconds)
# max_retries = 2             # Retry failed fetches this many times
# min_score_hn = 50           # Minimum score for Hacker News items
# min_score_reddit = 50       # Minimum score for Reddit items
# min_words_blog = 40         # Skip blog posts shorter than this

# [summary]
# summary_backend = "cli"     # "cli" (Claude Code) or "api" (ANTHROPIC_API_KEY)
# summary_model = "claude-haiku-4-5-20251001"
# summary_workers = 4         # Parallel summarization threads
# summary_prompt = "..."      # Custom system prompt for summaries

# [cache]
# cache_prune_days = 60       # Delete items older than this

# [html]
# open_browser = true         # Auto-open generated HTML in browser
# html_path = "~/.clankernewsdump/feed.html"

# [sources]
# # Add your own RSS feeds (appended to built-in list)
# extra_feeds = [
#     {name = "My Blog", url = "https://example.com/feed.xml", category = "blog"},
# ]
# extra_subreddits = ["LangChain"]
# extra_hn_queries = ["RAG"]
'''
    CONFIG_PATH.write_text(template)
    return CONFIG_PATH
