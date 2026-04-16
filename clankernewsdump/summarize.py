"""Summarize news items via either:
1. Local Claude Code CLI (`claude -p`) -- uses your subscription, no API key. [default]
2. Anthropic API (`--backend api`) -- uses ANTHROPIC_API_KEY, billed per token.

Both cache in SQLite to avoid re-summarizing.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys

from . import cache
from . import config as cfg
from .models import Item

log = logging.getLogger("clankernewsdump")


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _build_prompt(item: Item) -> str:
    system = cfg.get("summary_prompt")
    content = _strip_html(item.snippet)[:2000]
    return (
        f"{system}\n\n"
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
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        result = subprocess.run(cmd, **kwargs)
    except FileNotFoundError:
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
            log.error("CLI launch failed for %s: %s", item.title[:40], e)
            return f"[cli launch failed: {e}]"
    except subprocess.TimeoutExpired:
        log.warning("Summary timeout for: %s", item.title[:60])
        return "[summary timeout]"
    except Exception as e:
        log.error("CLI failed for %s: %s", item.title[:40], e)
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
    model = cfg.get("summary_model")
    max_tokens = cfg.get("summary_max_tokens")
    system = cfg.get("summary_prompt")

    if _api_client is None:
        from anthropic import Anthropic
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return "[ANTHROPIC_API_KEY not set]"
        _api_client = Anthropic()
    prompt = _build_prompt(item)
    try:
        msg = _api_client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        log.error("API summarization failed for %s: %s", item.title[:40], e)
        return f"[api failed: {e}]"


# ---------- Dispatcher ----------


def set_backend(backend: str) -> None:
    cfg.override("summary_backend", backend)


def summarize_item(item: Item) -> str:
    cached = cache.get_summary(item.url)
    if cached:
        return cached
    backend = cfg.get("summary_backend")
    summary = _summarize_via_api(item) if backend == "api" else _summarize_via_cli(item)
    if summary and not summary.startswith("["):
        cache.put_summary(item.url, summary)
    return summary
