"""Summarize news items via either:
1. Local Claude Code CLI (`claude -p`) — uses your subscription, no API key. [default]
2. Anthropic API (`--api` flag) — uses ANTHROPIC_API_KEY, billed per token.

Both cache in SQLite to avoid re-summarizing.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

from . import cache
from .models import Item

MODEL = "claude-haiku-4-5-20251001"

SYSTEM = (
    "You summarize AI/ML news items for a busy engineering manager. "
    "Write exactly 2 sentences: first what happened, second why it matters. "
    "Be concrete and specific. No hype words. No preamble. Output only the summary, nothing else."
)


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _build_prompt(item: Item) -> str:
    content = _strip_html(item.snippet)[:2000]
    return (
        f"{SYSTEM}\n\n"
        f"Source: {item.source}\n"
        f"Title: {item.title}\n"
        f"Content: {content or '(no body available - summarize from title only)'}"
    )


# ---------- Claude Code CLI backend ----------

_claude_bin: str | None = None


def _find_claude() -> str | None:
    global _claude_bin
    if _claude_bin is not None:
        return _claude_bin or None
    # Try a few plausible names on Windows
    for candidate in ("claude", "claude.cmd", "claude.exe"):
        path = shutil.which(candidate)
        if path:
            _claude_bin = path
            return path
    _claude_bin = ""
    return None


def _summarize_via_cli(item: Item) -> str:
    claude_bin = _find_claude()
    if not claude_bin:
        return "[claude CLI not found on PATH]"
    prompt = _build_prompt(item)

    # On Windows, .cmd files need shell=True or must be invoked via cmd.exe
    # to avoid "not a valid Win32 application" errors. Safest portable form:
    # pipe the prompt via stdin so we never touch command-line quoting.
    is_windows = sys.platform == "win32"
    cmd = [claude_bin, "-p"]

    try:
        kwargs = dict(
            input=prompt,
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            errors="replace",
        )
        if is_windows:
            # CREATE_NO_WINDOW prevents a console flash from the .cmd wrapper.
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        result = subprocess.run(cmd, **kwargs)
    except FileNotFoundError:
        # .cmd wrapper resolution failure — retry via cmd.exe
        try:
            result = subprocess.run(
                ["cmd.exe", "/c", claude_bin, "-p"],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=120,
                encoding="utf-8",
                errors="replace",
            )
        except Exception as e:
            return f"[cli launch failed: {e}]"
    except subprocess.TimeoutExpired:
        return "[summary timeout]"
    except Exception as e:
        return f"[cli failed: {e}]"

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        last = stderr.splitlines()[-1] if stderr else "unknown error"
        return f"[cli error rc={result.returncode}: {last[:200]}]"

    out = (result.stdout or "").strip()
    if not out:
        return "[cli returned empty output]"
    return out


# ---------- Anthropic API backend ----------

_api_client = None


def _summarize_via_api(item: Item) -> str:
    global _api_client
    if _api_client is None:
        from anthropic import Anthropic
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return "[ANTHROPIC_API_KEY not set]"
        _api_client = Anthropic()
    prompt = _build_prompt(item)
    try:
        msg = _api_client.messages.create(
            model=MODEL,
            max_tokens=200,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        return f"[api failed: {e}]"


# ---------- Dispatcher ----------

_backend = "cli"


def set_backend(backend: str) -> None:
    global _backend
    _backend = backend


def summarize_item(item: Item) -> str:
    cached = cache.get_summary(item.url)
    if cached:
        return cached
    summary = _summarize_via_api(item) if _backend == "api" else _summarize_via_cli(item)
    # Only cache successful summaries (errors start with '[')
    if summary and not summary.startswith("["):
        cache.put_summary(item.url, summary)
    return summary
