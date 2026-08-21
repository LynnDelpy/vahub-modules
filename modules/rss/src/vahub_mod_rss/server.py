"""The RSS module: the latest items from your feeds, as read-only tools.

It answers the dashboard card's question, what is new across the feeds you
follow, and lets the assistant look at one feed or search across them. It fetches
each feed over HTTP and parses it with feedparser, which handles RSS and Atom and
the many ways a feed can be slightly malformed. It never writes.

Each feed is fetched with httpx (async), then parsed in a worker thread, because
feedparser is regex-heavy and blocking. As in every module here, the parsing is
done by helpers the tests call directly, and a feed that is unreachable or
malformed is reported as a value (in `errors`) rather than raised.
"""

from __future__ import annotations

import asyncio
import calendar as _calendar
import html
import os
import re
import time
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import feedparser
import httpx
from mcp.server.fastmcp import FastMCP

FEEDS = os.environ.get("RSS_FEEDS") or ""
USER_AGENT = "vahub-mod-rss/0.1 (+https://github.com/LynnDelpy/vahub-modules)"
UTC = ZoneInfo("UTC")

mcp = FastMCP("rss")


def _timeout() -> float:
    try:
        return max(1.0, float(os.environ.get("RSS_TIMEOUT_S") or "12"))
    except ValueError:
        return 12.0


def _max_per_feed() -> int:
    try:
        return max(1, min(int(os.environ.get("RSS_MAX_PER_FEED") or "25"), 100))
    except ValueError:
        return 25


def _clamp(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(int(value), hi))
    except (TypeError, ValueError):
        return default


_http = httpx.AsyncClient(timeout=_timeout(), follow_redirects=True, headers={"user-agent": USER_AGENT})


# --------------------------------------------------------------------------
# pure parsing helpers (the tests call these directly)
# --------------------------------------------------------------------------
def split_feeds(raw: str) -> list[str]:
    """Feed URLs come as one string (whitespace, comma or newline separated)."""
    return [part for part in re.split(r"[\s,]+", raw.strip()) if part]


def _host(url: str) -> str:
    try:
        return urlsplit(url).netloc or url
    except ValueError:
        return url


def strip_html(text: str) -> str:
    """A feed summary is often HTML. Reduce it to readable plain text: drop tags,
    unescape entities, collapse whitespace. Not a sanitiser (nothing here renders
    it), just a way to keep a card and the model from swallowing markup."""
    without_tags = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()


def published_epoch(entry: Any) -> float | None:
    """A comparable timestamp for an entry, from whichever date field it carries.
    feedparser normalises the parsed date to UTC, so timegm is the right inverse."""
    for field in ("published_parsed", "updated_parsed"):
        value = entry.get(field) if hasattr(entry, "get") else None
        if value is not None:
            try:
                return float(_calendar.timegm(value))
            except (TypeError, ValueError, OverflowError):
                continue
    return None


def make_item(entry: Any, feed_title: str) -> dict[str, Any]:
    """One feed entry as the fields a card and the assistant use. Carries a
    private ``_sort`` epoch (None sorts last) so items from different feeds merge
    into one newest-first list; :func:`public` strips it before returning."""
    epoch = published_epoch(entry)
    summary = entry.get("summary") if hasattr(entry, "get") else None
    published = datetime.fromtimestamp(epoch, tz=UTC).isoformat() if epoch is not None else None
    return {
        "feed": feed_title,
        "title": strip_html(str(entry.get("title") or "")) or None,
        "link": entry.get("link") or None,
        "published": published,
        "summary": (strip_html(str(summary))[:500] or None) if summary is not None else None,
        "_sort": epoch,
    }


def parse_feed(raw: bytes, source: str) -> dict[str, Any]:
    """Title and items for one feed's raw bytes. Each item carries the source
    host privately (in ``_host``) so the feed tool can match on it as well as on
    the title; :func:`public` strips it before returning."""
    parsed = feedparser.parse(raw)
    feed_title = str((parsed.feed.get("title") if parsed.feed else "") or "").strip() or _host(source)
    host = _host(source)
    limit = _max_per_feed()
    items = []
    for entry in parsed.entries[:limit]:
        item = make_item(entry, feed_title)
        item["_host"] = host
        items.append(item)
    return {"feed": feed_title, "items": items}


def public(item: dict[str, Any]) -> dict[str, Any]:
    """An item without the internal sort key, for returning to the caller."""
    return {k: v for k, v in item.items() if not k.startswith("_")}


def _sort_key(item: dict[str, Any]) -> float:
    # Newest first; an item with no date sorts to the very end.
    epoch = item.get("_sort")
    return epoch if isinstance(epoch, int | float) else float("-inf")


def _matches(item: dict[str, Any], needle: str) -> bool:
    hay = " ".join(str(item.get(field) or "") for field in ("title", "summary", "feed")).lower()
    return needle in hay


def feed_match(item: dict[str, Any], needle: str) -> bool:
    """Whether an item belongs to a feed the caller named by part of its title or
    its host. Matching on the host is why parse_feed records ``_host``."""
    return needle in str(item.get("feed") or "").lower() or needle in str(item.get("_host") or "").lower()


# --------------------------------------------------------------------------
# network work
# --------------------------------------------------------------------------
async def _one_feed(url: str, items: list[dict[str, Any]], errors: list[str]) -> None:
    try:
        response = await _http.get(url)
        response.raise_for_status()
    except Exception as e:  # a bad feed is reported as a value, never a crash
        errors.append(f"{_host(url)}: {e}")
        return
    try:
        parsed = await asyncio.to_thread(parse_feed, response.content, url)
    except Exception as e:
        errors.append(f"{_host(url)}: cannot parse: {e}")
        return
    items.extend(parsed["items"])


async def _collect() -> tuple[list[dict[str, Any]], list[str]]:
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    await asyncio.gather(*(_one_feed(url, items, errors) for url in split_feeds(FEEDS)))
    items.sort(key=_sort_key, reverse=True)
    return items, errors


# --------------------------------------------------------------------------
# tools
# --------------------------------------------------------------------------
@mcp.tool()
async def summary(limit: int = 10) -> dict[str, Any]:
    """The most recent items across all feeds, for the dashboard card.

    limit: how many items to return (1 to 50).
    """
    if not split_feeds(FEEDS):
        return {"configured": False, "error": "not configured: set RSS_FEEDS"}
    items, errors = await _collect()
    capped = _clamp(limit, 10, 1, 50)
    return {
        "configured": True,
        "feeds": len(split_feeds(FEEDS)),
        "count": len(items),
        "items": [public(i) for i in items[:capped]],
        "errors": errors or None,
    }


@mcp.tool()
async def latest(limit: int = 20) -> dict[str, Any]:
    """The most recent items across all your feeds, newest first.

    limit: how many to return (1 to 100).
    """
    if not split_feeds(FEEDS):
        return {"error": "not configured: set RSS_FEEDS"}
    items, errors = await _collect()
    capped = _clamp(limit, 20, 1, 100)
    return {"count": len(items), "items": [public(i) for i in items[:capped]], "errors": errors or None}


@mcp.tool()
async def feed(name: str, limit: int = 20) -> dict[str, Any]:
    """Items from one feed, matched by its title (or host) containing `name`.

    name: part of the feed's title or URL host.
    limit: how many to return (1 to 100).
    """
    if not split_feeds(FEEDS):
        return {"error": "not configured: set RSS_FEEDS"}
    items, errors = await _collect()
    needle = name.strip().lower()
    hits = [public(i) for i in items if feed_match(i, needle)] if needle else []
    capped = _clamp(limit, 20, 1, 100)
    return {"name": name, "count": len(hits), "items": hits[:capped], "errors": errors or None}


@mcp.tool()
async def search(query: str, limit: int = 20) -> dict[str, Any]:
    """Find items whose title, summary or feed matches a query.

    query: text to look for.
    limit: how many to return (1 to 100).
    """
    if not split_feeds(FEEDS):
        return {"error": "not configured: set RSS_FEEDS"}
    items, errors = await _collect()
    needle = query.strip().lower()
    hits = [public(i) for i in items if _matches(i, needle)] if needle else []
    capped = _clamp(limit, 20, 1, 100)
    return {"query": query, "count": len(hits), "items": hits[:capped], "errors": errors or None}


@mcp.tool(name="__health")
async def health() -> dict[str, Any]:
    """Reserved health probe: can we fetch and parse the first feed?"""
    feeds = split_feeds(FEEDS)
    if not feeds:
        return {"ok": False, "backend": "rss", "latency_ms": None, "detail": "RSS_FEEDS is not set"}
    started = time.monotonic()
    try:
        # Bound the probe below the manifest's health.timeout_s (10s).
        response = await _http.get(feeds[0], timeout=min(_timeout(), 8.0))
        response.raise_for_status()
        parsed = await asyncio.to_thread(feedparser.parse, response.content)
        return {
            "ok": True,
            "backend": _host(feeds[0]),
            "latency_ms": round((time.monotonic() - started) * 1000, 1),
            "detail": None if parsed.entries else "feed parsed but had no entries",
        }
    except Exception as e:
        return {"ok": False, "backend": _host(feeds[0]), "latency_ms": None, "detail": str(e)}


def run() -> None:
    mcp.run(transport="stdio")
