"""Swiss public transport: connections and departure boards.

Backed by transport.opendata.ch, which needs no key and no account, so this
module is read-only and has nothing to redact. Two things it insists on:

* Every value the API returns is treated as optional. The upstream shape is
  documented but not guaranteed, and a KeyError inside a tool becomes an error
  the user hears instead of a departure time.
* Times come back as ISO strings with an offset and durations as "00d00:23:00".
  Both are rewritten into what a person would say ("07:52", "23 min"), because
  the result is usually read aloud.

Config (optional): TRANSIT_API_URL, TZ_DEFAULT.
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from mcp.server.fastmcp import FastMCP

BASE_URL = os.environ.get("TRANSIT_API_URL", "https://transport.opendata.ch/v1").rstrip("/")
TZ_DEFAULT = os.environ.get("TZ_DEFAULT", "Europe/Zurich")
USER_AGENT = "vahub-mod-transit/0.1 (+https://github.com/LynnDelpy/vahub-modules)"

mcp = FastMCP("transit")
_client = httpx.AsyncClient(base_url=BASE_URL, timeout=12.0, headers={"user-agent": USER_AGENT})


def zone() -> ZoneInfo:
    try:
        return ZoneInfo(TZ_DEFAULT)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("Europe/Zurich")


def clock(iso: str | None) -> str | None:
    """"2026-07-27T07:52:00+0200" to "07:52". Unparseable input is passed
    through rather than dropped, so a format change degrades instead of hiding
    the departure."""
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso).strftime("%H:%M")
    except (ValueError, TypeError):
        return iso if isinstance(iso, str) else None


def duration(value: str | None) -> str | None:
    """"00d00:23:00" to "23 min", "00d01:05:00" to "1h05"."""
    if not isinstance(value, str):
        return None
    try:
        days, hms = value.split("d")
        hours, minutes, _seconds = hms.split(":")
        total = int(days) * 1440 + int(hours) * 60 + int(minutes)
    except (ValueError, AttributeError):
        return value
    hh, mm = divmod(total, 60)
    return f"{hh}h{mm:02d}" if hh else f"{mm} min"


def _station_name(node: Any) -> str | None:
    if not isinstance(node, dict):
        return None
    station = node.get("station")
    return station.get("name") if isinstance(station, dict) else None


def _time_at(node: Any, key: str) -> str | None:
    return clock(node.get(key)) if isinstance(node, dict) else None


def _line_label(node: dict[str, Any]) -> str | None:
    category = str(node.get("category") or "").strip()
    number = str(node.get("number") or node.get("name") or "").strip()
    return f"{category} {number}".strip() or None


def legs(sections: Any) -> list[dict[str, Any]]:
    """Flatten a journey into the steps a person would describe: which line from
    where to where, and the walks in between."""
    out: list[dict[str, Any]] = []
    for section in sections if isinstance(sections, list) else []:
        if not isinstance(section, dict):
            continue
        departure = section.get("departure")
        arrival = section.get("arrival")
        journey = section.get("journey")
        if isinstance(journey, dict):
            out.append(
                {
                    "line": _line_label(journey),
                    "from": _station_name(departure),
                    "to": _station_name(arrival),
                    "departure": _time_at(departure, "departure"),
                    "arrival": _time_at(arrival, "arrival"),
                }
            )
        elif section.get("walk"):
            out.append({"walk": True, "from": _station_name(departure), "to": _station_name(arrival)})
    return out


def _clamp(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(int(value), hi))
    except (TypeError, ValueError):
        return default


def summarize_connections(payload: Any, limit: int) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    raw = payload.get("connections")
    out: list[dict[str, Any]] = []
    for connection in (raw if isinstance(raw, list) else [])[:limit]:
        if not isinstance(connection, dict):
            continue
        start = connection.get("from") if isinstance(connection.get("from"), dict) else {}
        end = connection.get("to") if isinstance(connection.get("to"), dict) else {}
        out.append(
            {
                "depart": clock(start.get("departure")),
                "arrive": clock(end.get("arrival")),
                "from": _station_name(start),
                "to": _station_name(end),
                "duration": duration(connection.get("duration")),
                "transfers": connection.get("transfers"),
                "legs": legs(connection.get("sections")),
            }
        )
    return out


def summarize_board(payload: Any, limit: int) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    raw = payload.get("stationboard")
    out: list[dict[str, Any]] = []
    for entry in (raw if isinstance(raw, list) else [])[:limit]:
        if not isinstance(entry, dict):
            continue
        stop = entry.get("stop") if isinstance(entry.get("stop"), dict) else {}
        out.append(
            {
                "line": _line_label(entry),
                "to": entry.get("to"),
                "departure": clock(stop.get("departure")),
                "platform": stop.get("platform"),
            }
        )
    return out


@mcp.tool()
async def find_connections(
    origin: str,
    destination: str,
    arrive_by: str | None = None,
    depart_at: str | None = None,
    date: str | None = None,
    limit: int = 4,
) -> dict[str, Any]:
    """Find public transport connections between two places in Switzerland.

    origin, destination: stop or place names. Include the town for a street
      address ("Haldenweg 15, Basel"); station names look like "Basel SBB".
    arrive_by: desired arrival time as "HH:MM". Returns journeys arriving by then.
    depart_at: desired departure time as "HH:MM". Ignored when arrive_by is set.
    date: "YYYY-MM-DD". Defaults to today.
    limit: how many journeys to return (1 to 6).
    """
    capped = _clamp(limit, 4, 1, 6)
    params: dict[str, Any] = {
        "from": origin,
        "to": destination,
        "limit": capped,
        "date": date or datetime.now(zone()).strftime("%Y-%m-%d"),
    }
    if arrive_by:
        params["time"] = arrive_by
        params["isArrivalTime"] = 1
    elif depart_at:
        params["time"] = depart_at

    response = await _client.get("/connections", params=params)
    response.raise_for_status()
    return {
        "from": origin,
        "to": destination,
        "date": params["date"],
        "arrive_by": arrive_by,
        "depart_at": depart_at,
        "connections": summarize_connections(response.json(), capped),
    }


@mcp.tool()
async def next_departures(station: str, limit: int = 6) -> dict[str, Any]:
    """Upcoming departures from one station, as a departure board.

    station: station name, for example "Basel SBB".
    limit: how many departures to return (1 to 12).
    """
    capped = _clamp(limit, 6, 1, 12)
    response = await _client.get("/stationboard", params={"station": station, "limit": capped})
    response.raise_for_status()
    payload = response.json()
    resolved = payload.get("station") if isinstance(payload, dict) else None
    name = resolved.get("name") if isinstance(resolved, dict) else None
    return {"station": name or station, "departures": summarize_board(payload, capped)}


@mcp.tool(name="__health")
async def health() -> dict[str, Any]:
    """Reserved health probe: does the transit API answer?"""
    started = time.monotonic()
    try:
        response = await _client.get("/stationboard", params={"station": "Basel SBB", "limit": 1})
        ok = response.status_code == 200
        return {
            "ok": ok,
            "backend": "transport.opendata.ch",
            "latency_ms": round((time.monotonic() - started) * 1000, 1),
            "detail": None if ok else f"status {response.status_code}",
        }
    except Exception as e:
        # A probe reports failures, it never raises them: the hub marks the
        # module degraded, and an exception here would look like a crash.
        return {"ok": False, "backend": "transport.opendata.ch", "latency_ms": None, "detail": str(e)}


def run() -> None:
    mcp.run(transport="stdio")
