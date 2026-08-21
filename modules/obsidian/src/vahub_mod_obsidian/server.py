"""The Obsidian module: a read-only view of a vault of Markdown notes.

It answers the dashboard card's question, what is in today's daily note and what
have I touched recently, and lets the assistant search the vault or read one
note. It only ever reads: there is no tool that writes, moves or deletes a file.

Two boundaries hold here. The module reads only files under a single root: the
vault path, optionally narrowed to a subdirectory (`OBSIDIAN_SUBDIR`), so you can
expose just `Projects/` and keep the rest of a vault out of reach. And every path
a tool is handed is resolved and checked to be inside that root before it is
opened, so a `../` or an absolute path cannot escape it. Hidden directories (a
leading dot, such as `.obsidian` or `.git`) are skipped, and only Markdown files
are ever read.

The disk work runs in a worker thread, and the parsing helpers are called
directly by the tests.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from mcp.server.fastmcp import FastMCP

VAULT_PATH = os.environ.get("OBSIDIAN_VAULT_PATH") or ""
SUBDIR = os.environ.get("OBSIDIAN_SUBDIR") or ""
DAILY_DIR = os.environ.get("OBSIDIAN_DAILY_DIR") or ""
DAILY_FORMAT = os.environ.get("OBSIDIAN_DAILY_FORMAT") or "%Y-%m-%d"

MARKDOWN_EXTS = {".md", ".markdown"}
MAX_BYTES = 200_000  # a single note read is capped, so no note can flood a reply
MAX_FILES = 5000  # a vault scan is bounded, so a huge vault cannot hang a call
TITLE_SCAN_BYTES = 4096  # enough of a note to find its first heading

mcp = FastMCP("obsidian")


def _tz() -> ZoneInfo:
    name = (os.environ.get("TZ_DEFAULT") or "").strip()
    for candidate in (name, "UTC"):
        if not candidate:
            continue
        try:
            return ZoneInfo(candidate)
        except (ZoneInfoNotFoundError, ValueError):
            continue
    return ZoneInfo("UTC")


def _clamp(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(int(value), hi))
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------
# pure filesystem helpers (the tests call these directly)
# --------------------------------------------------------------------------
def resolve_root(vault: str, subdir: str) -> Path | None:
    """The single directory every read is confined to: the vault, narrowed to
    ``subdir`` if one is set. Returns None if the vault is unset, missing, or the
    subdirectory would escape it."""
    if not vault.strip():
        return None
    try:
        base = Path(vault).expanduser().resolve()
        if not base.is_dir():
            return None
        if not subdir.strip():
            return base
        root = (base / subdir).resolve()
    except (OSError, ValueError):
        return None
    if root != base and not root.is_relative_to(base):
        return None
    return root if root.is_dir() else None


def safe_join(root: Path, rel: str) -> Path | None:
    """Resolve a caller-supplied vault-relative path and confirm it is a Markdown
    file inside ``root``. An absolute path, a ``..`` escape, a symlink pointing
    out, a non-Markdown file, or a missing file all return None."""
    rel = (rel or "").strip()
    if not rel:
        return None
    try:
        candidate = (root / rel).resolve()
    except (OSError, ValueError):
        # resolve() does filesystem syscalls and can raise on a malformed path
        # (an embedded null byte raises ValueError; a symlink loop raises OSError).
        # A path we cannot resolve is simply not a note: report it, do not raise.
        return None
    if candidate != root and not candidate.is_relative_to(root):
        return None
    if candidate.suffix.lower() not in MARKDOWN_EXTS or not candidate.is_file():
        return None
    return candidate


def iter_markdown(root: Path, cap: int = MAX_FILES) -> list[Path]:
    """Every Markdown file under ``root``, skipping hidden directories. Bounded by
    ``cap`` so a very large vault cannot make a scan run away.

    A file whose resolved path escapes ``root`` (a symlink pointing outside the
    vault) is skipped, so the bulk scan is confined exactly as :func:`safe_join`
    confines the note tool. os.walk does not follow symlinked directories, so
    only files need this check."""
    base = root.resolve()
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            if Path(name).suffix.lower() not in MARKDOWN_EXTS:
                continue
            full = Path(dirpath) / name
            try:
                if not full.resolve().is_relative_to(base):
                    continue  # a symlink whose target is outside the vault
            except OSError:
                continue
            out.append(full)
            if len(out) >= cap:
                return out
    return out


def safe_read(path: Path, max_bytes: int = MAX_BYTES) -> str | None:
    """A note's text, capped, or None if it cannot be read."""
    try:
        return path.read_bytes()[:max_bytes].decode("utf-8", "replace")
    except OSError:
        return None


def _strip_frontmatter(text: str) -> str:
    """Drop a leading YAML frontmatter block (``---`` ... ``---``) if present."""
    if not text.startswith("---"):
        return text
    closing = re.search(r"\n---[ \t]*\r?\n", text)
    return text[closing.end() :] if closing else text


def note_title(path: Path, text: str) -> str:
    """A note's first ``# `` heading, or its filename stem if it has none."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return path.stem


def excerpt(text: str, limit: int = 280) -> str:
    """A short plain-text preview: frontmatter dropped, whitespace collapsed."""
    body = _strip_frontmatter(text)
    return re.sub(r"\s+", " ", body).strip()[:limit]


def _snippet(text: str, needle: str, radius: int = 120) -> str | None:
    index = text.lower().find(needle)
    if index < 0:
        return None
    start = max(0, index - radius)
    end = min(len(text), index + len(needle) + radius)
    body = re.sub(r"\s+", " ", text[start:end]).strip()
    return ("…" if start > 0 else "") + body + ("…" if end < len(text) else "")


def _mtime_iso(path: Path, tz: ZoneInfo) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz).isoformat()
    except OSError:
        return None


def _note_meta(path: Path, root: Path, tz: ZoneInfo) -> dict[str, Any]:
    text = safe_read(path, TITLE_SCAN_BYTES) or ""
    return {
        "path": path.relative_to(root).as_posix(),
        "title": note_title(path, text),
        "modified": _mtime_iso(path, tz),
    }


def search_notes(root: Path, query: str, limit: int, tz: ZoneInfo) -> list[dict[str, Any]]:
    """Notes whose filename or content contains ``query``, with a matching
    snippet. Filename matches that have no body hit fall back to an excerpt."""
    needle = query.strip().lower()
    if not needle:
        return []
    results: list[dict[str, Any]] = []
    for path in iter_markdown(root):
        text = safe_read(path)
        if text is None:
            continue
        in_name = needle in path.name.lower()
        in_body = needle in text.lower()
        if not (in_name or in_body):
            continue
        results.append(
            {
                "path": path.relative_to(root).as_posix(),
                "title": note_title(path, text),
                "snippet": _snippet(text, needle) or excerpt(text, 160),
                "modified": _mtime_iso(path, tz),
            }
        )
        if len(results) >= limit:
            break
    return results


def recent_notes(root: Path, limit: int, tz: ZoneInfo) -> list[dict[str, Any]]:
    files = iter_markdown(root)
    files.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0.0, reverse=True)
    return [_note_meta(path, root, tz) for path in files[:limit]]


def daily_path(root: Path, daily_dir: str, fmt: str, day: Any) -> Path | None:
    """Where a daily note for ``day`` would live, or None if that would fall
    outside the root. The file need not exist; the caller checks."""
    name = day.strftime(fmt or "%Y-%m-%d") + ".md"
    rel = f"{daily_dir.strip('/')}/{name}" if daily_dir.strip() else name
    try:
        candidate = (root / rel).resolve()
    except (OSError, ValueError):
        return None
    if candidate != root and not candidate.is_relative_to(root):
        return None
    return candidate


# --------------------------------------------------------------------------
# glue
# --------------------------------------------------------------------------
def _root() -> Path | None:
    return resolve_root(VAULT_PATH, SUBDIR)


def _config_error() -> str:
    if not VAULT_PATH.strip():
        return "not configured: set OBSIDIAN_VAULT_PATH"
    return f"vault path not usable (missing, not a directory, or bad OBSIDIAN_SUBDIR): {VAULT_PATH}"


def _summary_sync(root: Path) -> dict[str, Any]:
    tz = _tz()
    today = datetime.now(tz).date()
    today_note: dict[str, Any] | None = None
    dp = daily_path(root, DAILY_DIR, DAILY_FORMAT, today)
    if dp is not None and dp.is_file():
        text = safe_read(dp) or ""
        today_note = {
            "path": dp.relative_to(root).as_posix(),
            "title": note_title(dp, text),
            "excerpt": excerpt(text),
        }
    files = iter_markdown(root)
    files.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0.0, reverse=True)
    return {
        "configured": True,
        "vault": root.name,
        "note_count": len(files),
        "today": today_note,
        "recent": [_note_meta(path, root, tz) for path in files[:5]],
    }


def _daily_sync(root: Path, date: str | None) -> dict[str, Any]:
    tz = _tz()
    if date:
        try:
            day = datetime.strptime(date.strip(), "%Y-%m-%d").date()
        except ValueError:
            return {"error": f"invalid date {date!r}, expected YYYY-MM-DD"}
    else:
        day = datetime.now(tz).date()
    dp = daily_path(root, DAILY_DIR, DAILY_FORMAT, day)
    if dp is None:
        return {"error": "the daily note path resolves outside the vault"}
    rel = dp.relative_to(root).as_posix() if dp.is_relative_to(root) else None
    if not dp.is_file():
        return {"date": day.isoformat(), "exists": False, "path": rel}
    text = safe_read(dp) or ""
    return {
        "date": day.isoformat(),
        "exists": True,
        "path": rel,
        "title": note_title(dp, text),
        "content": text,
        "modified": _mtime_iso(dp, tz),
    }


def _note_sync(root: Path, path: str) -> dict[str, Any]:
    target = safe_join(root, path)
    if target is None:
        return {"error": "note not found, not Markdown, or outside the vault"}
    text = safe_read(target)
    if text is None:
        return {"error": "cannot read the note"}
    return {
        "path": target.relative_to(root).as_posix(),
        "title": note_title(target, text),
        "content": text,
        "modified": _mtime_iso(target, _tz()),
    }


# --------------------------------------------------------------------------
# tools
# --------------------------------------------------------------------------
@mcp.tool()
async def summary() -> dict[str, Any]:
    """Today's daily note and the notes touched most recently, for the card."""
    root = _root()
    if root is None:
        return {"configured": False, "error": _config_error()}
    return await asyncio.to_thread(_summary_sync, root)


@mcp.tool()
async def daily(date: str | None = None) -> dict[str, Any]:
    """The daily note for a date (default today).

    date: an ISO date, YYYY-MM-DD. Omit for today.
    """
    root = _root()
    if root is None:
        return {"error": _config_error()}
    return await asyncio.to_thread(_daily_sync, root, date)


@mcp.tool()
async def search(query: str, limit: int = 20) -> dict[str, Any]:
    """Find notes whose filename or content matches a query.

    query: text to look for.
    limit: how many notes to return (1 to 100).
    """
    root = _root()
    if root is None:
        return {"error": _config_error()}
    capped = _clamp(limit, 20, 1, 100)
    results = await asyncio.to_thread(search_notes, root, query, capped, _tz())
    return {"query": query, "count": len(results), "results": results}


@mcp.tool()
async def note(path: str) -> dict[str, Any]:
    """Read one note by its vault-relative path.

    path: a path inside the vault, e.g. "Projects/vahub.md".
    """
    root = _root()
    if root is None:
        return {"error": _config_error()}
    return await asyncio.to_thread(_note_sync, root, path)


@mcp.tool()
async def recent(limit: int = 20) -> dict[str, Any]:
    """The notes modified most recently, newest first.

    limit: how many to return (1 to 100).
    """
    root = _root()
    if root is None:
        return {"error": _config_error()}
    capped = _clamp(limit, 20, 1, 100)
    notes = await asyncio.to_thread(recent_notes, root, capped, _tz())
    return {"count": len(notes), "notes": notes}


@mcp.tool(name="__health")
async def health() -> dict[str, Any]:
    """Reserved health probe: is the vault root present and readable?"""
    if not VAULT_PATH.strip():
        return {
            "ok": False,
            "backend": "obsidian",
            "latency_ms": None,
            "detail": "OBSIDIAN_VAULT_PATH is not set",
        }
    started = time.monotonic()
    root = _root()
    if root is None:
        return {"ok": False, "backend": VAULT_PATH, "latency_ms": None, "detail": _config_error()}
    ok = await asyncio.to_thread(lambda: root.is_dir() and os.access(root, os.R_OK))
    return {
        "ok": bool(ok),
        "backend": str(root),
        "latency_ms": round((time.monotonic() - started) * 1000, 1),
        "detail": None if ok else "vault root is not readable",
    }


def run() -> None:
    mcp.run(transport="stdio")
