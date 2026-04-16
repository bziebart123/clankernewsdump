"""Shared constants used across CLI, HTML generator, and export modules."""

CATEGORY_ORDER = [
    "subscribed", "blog", "newsletter", "lab", "podcast",
    "hn", "reddit", "arxiv", "news",
]

CATEGORY_LABELS = {
    "subscribed": "Subscribed",
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
    "subscribed": "#FFD700",
    "blog": "#00CED1",
    "newsletter": "#DA70D6",
    "lab": "#3CB371",
    "podcast": "#FFD700",
    "hn": "#FF8C00",
    "reddit": "#FF4500",
    "arxiv": "#6495ED",
    "news": "#B0B0B0",
}

# Rich markup styles (used by flat/CLI output)
CATEGORY_RICH_STYLES = {
    "subscribed": "bold gold1",
    "blog": "bold cyan",
    "newsletter": "bold magenta",
    "lab": "bold green",
    "podcast": "bold yellow",
    "hn": "bold orange1",
    "reddit": "bold red",
    "arxiv": "bold blue",
    "news": "bold white",
}


def escape_markup(s: str) -> str:
    """Escape Rich markup brackets."""
    return s.replace("[", "\\[").replace("]", "\\]")
