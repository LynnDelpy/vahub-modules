"""The time module: an MCP server over stdio that reports the current time.

This is the reference module. It has no backend, no credentials and no failure
modes worth speaking of, which makes it the one to read first and the one to
copy when writing your own. Two decisions here are deliberate and are repeated
in every other module in this repository:

* Tool functions are thin wrappers over plain helpers. The helpers hold the
  logic and the tests call them directly, so the suite does not depend on how
  the MCP SDK's decorator happens to wrap a function this month.
* An unusable timezone falls back instead of raising. The argument arrives from
  a language model, and a hallucinated zone name should produce the local time,
  not an error the user has to listen to.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from mcp.server.fastmcp import FastMCP

# Only the keys declared in module.yaml reach this process, so reading the
# environment directly is safe: there is nothing else in it.
DEFAULT_TZ = os.environ.get("TZ_DEFAULT", "UTC")

mcp = FastMCP("time")


def resolve_zone(tz: str | None) -> ZoneInfo:
    """First usable zone out of the argument, the configured default, and UTC."""
    for candidate in (tz, DEFAULT_TZ):
        if not candidate:
            continue
        try:
            return ZoneInfo(candidate)
        except (ZoneInfoNotFoundError, ValueError):
            continue
    return ZoneInfo("UTC")


def now_in(tz: str | None) -> datetime:
    return datetime.now(resolve_zone(tz))


def spoken_time(moment: datetime) -> str:
    """A phrase a text-to-speech voice can read without stumbling. No seconds,
    no timezone suffix, no ISO punctuation."""
    return f"It is {moment:%H:%M}."


@mcp.tool()
def get_current_time(tz: str | None = None) -> str:
    """Return the current date and time as an ISO-8601 string.

    tz: IANA timezone name such as "Europe/Zurich". Defaults to the timezone the
      module was configured with.
    """
    return now_in(tz).isoformat(timespec="seconds")


@mcp.tool()
def speak_current_time(tz: str | None = None) -> str:
    """Return the current time as a short phrase meant to be read aloud.

    Prefer this over get_current_time when the answer goes to a speaker.

    tz: IANA timezone name such as "Europe/Zurich". Defaults to the timezone the
      module was configured with.
    """
    return spoken_time(now_in(tz))


# __health is reserved by the module contract. The hub calls it on a timer to
# tell "the process is running" apart from "the thing it talks to answers", and
# it is never offered to the model. Every module must implement it and return
# {ok, backend, latency_ms, detail}.
@mcp.tool(name="__health")
def health() -> dict[str, Any]:
    """Reserved health probe."""
    return {"ok": True, "backend": "local clock", "latency_ms": 0.0, "detail": None}


def run() -> None:
    mcp.run(transport="stdio")
