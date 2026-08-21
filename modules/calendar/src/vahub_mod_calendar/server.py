"""The calendar module: upcoming events from ICS feed subscriptions, read-only.

It answers the dashboard card's question, what is on today and this week, and lets
the assistant look further out or search. It reads published iCalendar (.ics)
feeds over HTTP: the kind a Nextcloud or Radicale calendar exports, a Google
"secret address in iCal format", or any other subscription URL. It never writes:
there is no CalDAV, no login session that could change anything, only GET.

A feed is fetched with httpx (async), then parsed and its recurring events
expanded inside a worker thread, because parsing a large calendar is blocking.
As in every module here, the parsing is done by helpers the tests call directly,
and a feed that is unreachable or malformed is reported as a value (in `errors`)
rather than raised, so one bad feed never hides the others.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
import recurring_ical_events
from icalendar import Calendar
from mcp.server.fastmcp import FastMCP

ICS_URLS = os.environ.get("CALENDAR_ICS_URLS") or ""
USERNAME = (os.environ.get("CALENDAR_USERNAME") or "").strip()
PASSWORD = os.environ.get("CALENDAR_PASSWORD") or ""
USER_AGENT = "vahub-mod-calendar/0.1 (+https://github.com/LynnDelpy/vahub-modules)"
# A feed is read up to this size and no further. Parsing is pure-Python and its
# time scales with size, so an unbounded feed would let a health probe or a tool
# run far past its budget; a real calendar is nowhere near this large.
MAX_FEED_BYTES = 10_000_000

mcp = FastMCP("calendar")


def _timeout() -> float:
    try:
        return max(1.0, float(os.environ.get("CALENDAR_TIMEOUT_S") or "15"))
    except ValueError:
        return 15.0


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


_http = httpx.AsyncClient(timeout=_timeout(), follow_redirects=True, headers={"user-agent": USER_AGENT})


# --------------------------------------------------------------------------
# pure parsing helpers (the tests call these directly)
# --------------------------------------------------------------------------
def split_urls(raw: str) -> list[str]:
    """Feed URLs come as one string (whitespace, comma or newline separated)."""
    return [part for part in re.split(r"[\s,]+", raw.strip()) if part]


def _host(url: str) -> str:
    try:
        return urlsplit(url).netloc or url
    except ValueError:
        return url


def calendar_name(cal: Calendar, url: str) -> str:
    """A human label for the source: the calendar's own name if it declares one,
    otherwise the feed's host."""
    name = cal.get("X-WR-CALNAME")
    if name:
        text = str(name).strip()
        if text:
            return text
    return _host(url)


def _as_datetime(value: Any, tz: ZoneInfo) -> datetime | None:
    """Normalise an iCalendar date-or-datetime into a tz-aware datetime. A naive
    datetime is assumed to be in the configured zone; an all-day date becomes
    midnight there."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=tz) if value.tzinfo is None else value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=tz)
    return None


def serialize_event(component: Any, tz: ZoneInfo, source: str) -> dict[str, Any]:
    """One expanded VEVENT occurrence as the fields a card and the assistant use.
    Carries a private ``_sort`` epoch so occurrences from different feeds merge
    into one ordered list; callers strip it with :func:`public` before returning."""
    start_prop = component.get("dtstart")
    end_prop = component.get("dtend")
    start_val = start_prop.dt if start_prop is not None else None
    end_val = end_prop.dt if end_prop is not None else None
    all_day = isinstance(start_val, date) and not isinstance(start_val, datetime)
    start_dt = _as_datetime(start_val, tz)
    end_dt = _as_datetime(end_val, tz)
    summary = component.get("summary")
    location = component.get("location")
    return {
        "summary": str(summary) if summary is not None else "",
        "start": start_dt.isoformat() if start_dt is not None else None,
        "end": end_dt.isoformat() if end_dt is not None else None,
        "all_day": all_day,
        "location": (str(location) or None) if location is not None else None,
        "calendar": source,
        "_sort": start_dt.timestamp() if start_dt is not None else 0.0,
    }


def public(event: dict[str, Any]) -> dict[str, Any]:
    """An event without the internal sort key, for returning to the caller."""
    return {k: v for k, v in event.items() if not k.startswith("_")}


def expand_events(
    cal: Calendar, start: datetime, end: datetime, tz: ZoneInfo, source: str
) -> list[dict[str, Any]]:
    """Every occurrence in [start, end), recurring events expanded."""
    occurrences = recurring_ical_events.of(cal).between(start, end)
    return [serialize_event(component, tz, source) for component in occurrences]


def parse_and_expand(
    raw: bytes, url: str, start: datetime, end: datetime, tz: ZoneInfo
) -> list[dict[str, Any]]:
    cal = Calendar.from_ical(raw)
    return expand_events(cal, start, end, tz, calendar_name(cal, url))


def _end_of_day(moment: datetime) -> datetime:
    return moment.replace(hour=23, minute=59, second=59, microsecond=0)


def _matches(event: dict[str, Any], needle: str) -> bool:
    hay = " ".join(str(event.get(field) or "") for field in ("summary", "location", "calendar")).lower()
    return needle in hay


# --------------------------------------------------------------------------
# blocking / network work
# --------------------------------------------------------------------------
async def _fetch(url: str, timeout: float | None = None) -> bytes:
    auth = (USERNAME, PASSWORD) if USERNAME else None
    t = timeout if timeout is not None else _timeout()
    chunks: list[bytes] = []
    total = 0
    async with _http.stream("GET", url, auth=auth, timeout=t) as response:
        response.raise_for_status()
        async for chunk in response.aiter_bytes():
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_FEED_BYTES:
                # Stop reading rather than buffer an unbounded body: bounds both
                # memory and the parse time that follows.
                raise ValueError(f"feed larger than {MAX_FEED_BYTES // 1_000_000} MB")
    return b"".join(chunks)


async def _one_feed(
    url: str, start: datetime, end: datetime, tz: ZoneInfo, events: list[dict[str, Any]], errors: list[str]
) -> None:
    try:
        raw = await _fetch(url)
    except Exception as e:  # a bad feed is reported as a value, never a crash
        errors.append(f"{_host(url)}: {e}")
        return
    try:
        events.extend(await asyncio.to_thread(parse_and_expand, raw, url, start, end, tz))
    except Exception as e:
        errors.append(f"{_host(url)}: cannot parse: {e}")


async def _collect(start: datetime, end: datetime, tz: ZoneInfo) -> tuple[list[dict[str, Any]], list[str]]:
    events: list[dict[str, Any]] = []
    errors: list[str] = []
    await asyncio.gather(*(_one_feed(url, start, end, tz, events, errors) for url in split_urls(ICS_URLS)))
    events.sort(key=lambda e: e["_sort"])
    return events, errors


# --------------------------------------------------------------------------
# tools
# --------------------------------------------------------------------------
@mcp.tool()
async def summary() -> dict[str, Any]:
    """Counts for the dashboard card (today and the next seven days) and the next
    few upcoming events."""
    if not split_urls(ICS_URLS):
        return {"configured": False, "error": "not configured: set CALENDAR_ICS_URLS"}
    tz = _tz()
    now = datetime.now(tz)
    events, errors = await _collect(now, now + timedelta(days=7), tz)
    today_cutoff = _end_of_day(now).timestamp()
    today = [e for e in events if e["_sort"] <= today_cutoff]
    return {
        "configured": True,
        "feeds": len(split_urls(ICS_URLS)),
        "counts": {"today": len(today), "next_7_days": len(events)},
        "today": [public(e) for e in today[:10]],
        "upcoming": [public(e) for e in events[:5]],
        "errors": errors or None,
    }


@mcp.tool()
async def agenda(days: int = 7, limit: int = 50) -> dict[str, Any]:
    """Upcoming events over the next few days.

    days: how far ahead to look (1 to 90).
    limit: how many events to return (1 to 200).
    """
    if not split_urls(ICS_URLS):
        return {"error": "not configured: set CALENDAR_ICS_URLS"}
    tz = _tz()
    now = datetime.now(tz)
    horizon = _clamp(days, 7, 1, 90)
    events, errors = await _collect(now, now + timedelta(days=horizon), tz)
    capped = _clamp(limit, 50, 1, 200)
    return {"days": horizon, "events": [public(e) for e in events[:capped]], "errors": errors or None}


@mcp.tool()
async def search(query: str, days: int = 90, limit: int = 50) -> dict[str, Any]:
    """Find upcoming events whose title, location or calendar matches a query.

    query: text to look for.
    days: how far ahead to search (1 to 366).
    limit: how many to return (1 to 200).
    """
    if not split_urls(ICS_URLS):
        return {"error": "not configured: set CALENDAR_ICS_URLS"}
    tz = _tz()
    now = datetime.now(tz)
    horizon = _clamp(days, 90, 1, 366)
    events, errors = await _collect(now, now + timedelta(days=horizon), tz)
    needle = query.strip().lower()
    hits = [public(e) for e in events if _matches(e, needle)] if needle else []
    capped = _clamp(limit, 50, 1, 200)
    return {"query": query, "events": hits[:capped], "errors": errors or None}


@mcp.tool(name="__health")
async def health() -> dict[str, Any]:
    """Reserved health probe: can we fetch and parse the first feed?"""
    urls = split_urls(ICS_URLS)
    if not urls:
        return {"ok": False, "backend": "ics", "latency_ms": None, "detail": "CALENDAR_ICS_URLS is not set"}
    started = time.monotonic()
    budget = min(_timeout(), 8.0)

    async def _probe() -> None:
        raw = await _fetch(urls[0], timeout=budget)
        await asyncio.to_thread(Calendar.from_ical, raw)

    try:
        # A hard total deadline keeps the probe under the manifest's
        # health.timeout_s (10s), whatever the backend does: wait_for cancels a
        # slow fetch, and the size cap in _fetch bounds parse time. If the parse
        # thread is orphaned by a timeout it cannot extend this reply.
        await asyncio.wait_for(_probe(), timeout=budget)
        return {
            "ok": True,
            "backend": _host(urls[0]),
            "latency_ms": round((time.monotonic() - started) * 1000, 1),
            "detail": None,
        }
    except TimeoutError:
        return {
            "ok": False,
            "backend": _host(urls[0]),
            "latency_ms": None,
            "detail": f"probe exceeded {budget:.0f}s",
        }
    except Exception as e:
        return {"ok": False, "backend": _host(urls[0]), "latency_ms": None, "detail": str(e)}


def run() -> None:
    mcp.run(transport="stdio")
