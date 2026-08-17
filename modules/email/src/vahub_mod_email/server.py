"""The email module: a read-only view of a mailbox over IMAP.

It answers the dashboard card's question, how much unread mail is there and from
whom, and lets the assistant look at recent or matching messages. It is
deliberately read-only: it opens the mailbox with readonly=True and peeks at
headers, so nothing is ever sent, deleted, or even marked read. It never fetches
a message body.

IMAP is blocking, so every network call runs in a worker thread and never
touches the event loop. As in every module here, the header parsing is done by
helpers the tests call directly, and a backend failure is reported as a value.
"""

from __future__ import annotations

import asyncio
import contextlib
import email
import imaplib
import os
import time
from email.header import decode_header, make_header
from typing import Any

from mcp.server.fastmcp import FastMCP

HOST = (os.environ.get("EMAIL_HOST") or "").strip()
USERNAME = (os.environ.get("EMAIL_USERNAME") or "").strip()
PASSWORD = os.environ.get("EMAIL_PASSWORD") or ""
MAILBOX = os.environ.get("EMAIL_MAILBOX") or "INBOX"

mcp = FastMCP("email")


def _use_ssl() -> bool:
    return (os.environ.get("EMAIL_SSL") or "true").strip().lower() not in ("false", "0", "no", "off")


def _port() -> int:
    try:
        return int(os.environ.get("EMAIL_PORT") or (993 if _use_ssl() else 143))
    except ValueError:
        return 993 if _use_ssl() else 143


def _timeout() -> float:
    try:
        return max(1.0, float(os.environ.get("EMAIL_TIMEOUT_S") or "15"))
    except ValueError:
        return 15.0


def _clamp(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(int(value), hi))
    except (TypeError, ValueError):
        return default


def _missing_config() -> str | None:
    missing = [
        name
        for name, value in (
            ("EMAIL_HOST", HOST),
            ("EMAIL_USERNAME", USERNAME),
            ("EMAIL_PASSWORD", PASSWORD),
        )
        if not value
    ]
    return ("not configured: set " + ", ".join(missing)) if missing else None


# --------------------------------------------------------------------------
# pure header parsing (the tests call these directly)
# --------------------------------------------------------------------------
def decode_mime_header(value: Any) -> str:
    """Turn a possibly MIME-encoded header (=?utf-8?B?...?=) into plain text.
    A header that cannot be decoded is returned as its best-effort string rather
    than raising, because one odd message must not break the listing."""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return str(value)


def header_summary(raw: bytes) -> dict[str, Any]:
    """From the raw RFC822 header bytes of one message, the fields a card shows."""
    message = email.message_from_bytes(raw)
    return {
        "from": decode_mime_header(message.get("From")),
        "subject": decode_mime_header(message.get("Subject")),
        "date": message.get("Date"),
    }


def _imap_quote(text: str) -> str:
    """A safe IMAP quoted-string for a search term: strip CR/LF so it cannot
    inject a second command, and backslash-escape the two characters special
    inside a quoted string (backslash and double-quote) so a term containing them
    stays one valid string rather than silently matching nothing."""
    safe = text.replace("\r", " ").replace("\n", " ")[:200]
    safe = safe.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{safe}"'


def _extract_header_bytes(fetched: Any) -> bytes:
    """imaplib returns a fetch result as a list mixing tuples and flag strings;
    the header bytes are the second element of the tuple part."""
    for part in fetched or []:
        if isinstance(part, tuple) and len(part) >= 2 and isinstance(part[1], (bytes, bytearray)):
            return bytes(part[1])
    return b""


# --------------------------------------------------------------------------
# blocking IMAP work (runs in a worker thread)
# --------------------------------------------------------------------------
def _connect(timeout: float | None = None) -> imaplib.IMAP4:
    t = _timeout() if timeout is None else timeout
    if _use_ssl():
        conn: imaplib.IMAP4 = imaplib.IMAP4_SSL(HOST, _port(), timeout=t)
    else:
        conn = imaplib.IMAP4(HOST, _port(), timeout=t)
    conn.login(USERNAME, PASSWORD)
    return conn


def _logout(conn: imaplib.IMAP4) -> None:
    with contextlib.suppress(Exception):
        conn.logout()


def _one_header(conn: imaplib.IMAP4, mid: bytes) -> dict[str, Any]:
    _typ, data = conn.fetch(mid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
    return header_summary(_extract_header_bytes(data))


def _fetch_unread(limit: int) -> dict[str, Any]:
    conn = _connect()
    try:
        # readonly: opening the mailbox this way, and PEEKing, means nothing is
        # marked read just because the card looked at it.
        conn.select(MAILBOX, readonly=True)
        total = len(_ids(conn.search(None, "ALL")))
        unseen = _ids(conn.search(None, "UNSEEN"))
        recent = list(reversed(unseen))[:limit]  # newest first
        messages = [_one_header(conn, mid) for mid in recent]
        return {"unread": len(unseen), "total": total, "messages": messages}
    finally:
        _logout(conn)


def _search_text(text: str, limit: int) -> list[dict[str, Any]]:
    conn = _connect()
    try:
        conn.select(MAILBOX, readonly=True)
        ids = _ids(conn.search(None, "TEXT", _imap_quote(text)))
        recent = list(reversed(ids))[:limit]
        return [_one_header(conn, mid) for mid in recent]
    finally:
        _logout(conn)


def _ids(result: tuple[str, list[Any]]) -> list[bytes]:
    typ, data = result
    if typ != "OK" or not data or not data[0]:
        return []
    return data[0].split()


def _health_check() -> None:
    # Bound the probe below the manifest's health.timeout_s (10s). The work runs
    # in a thread the hub cannot cancel, so a silent-drop backend must be capped
    # here or the thread would run the full connection timeout past the budget.
    conn = _connect(timeout=min(_timeout(), 6.0))
    try:
        conn.select(MAILBOX, readonly=True)
    finally:
        _logout(conn)


# --------------------------------------------------------------------------
# tools
# --------------------------------------------------------------------------
@mcp.tool()
async def summary() -> dict[str, Any]:
    """Unread count, total count and the most recent few messages, for the card."""
    missing = _missing_config()
    if missing is not None:
        return {"configured": False, "error": missing}
    try:
        data = await asyncio.to_thread(_fetch_unread, 5)
    except Exception as e:
        return {"configured": True, "error": f"cannot read the mailbox: {e}"}
    return {
        "configured": True,
        "unread": data["unread"],
        "total": data["total"],
        "recent": data["messages"],
    }


@mcp.tool()
async def list_unread(limit: int = 20) -> dict[str, Any]:
    """Recent unread messages: from, subject and date. Does not mark them read.

    limit: how many to return (1 to 50).
    """
    missing = _missing_config()
    if missing is not None:
        return {"error": missing}
    capped = _clamp(limit, 20, 1, 50)
    try:
        data = await asyncio.to_thread(_fetch_unread, capped)
    except Exception as e:
        return {"error": f"cannot read the mailbox: {e}"}
    return {"unread": data["unread"], "total": data["total"], "messages": data["messages"]}


@mcp.tool()
async def search(query: str, limit: int = 20) -> dict[str, Any]:
    """Search the mailbox for messages whose text matches a query.

    query: text to look for (in headers and body, as the server implements it).
    limit: how many to return (1 to 50).
    """
    missing = _missing_config()
    if missing is not None:
        return {"error": missing}
    capped = _clamp(limit, 20, 1, 50)
    try:
        messages = await asyncio.to_thread(_search_text, query, capped)
    except Exception as e:
        return {"error": f"cannot search the mailbox: {e}"}
    return {"query": query, "messages": messages}


@mcp.tool(name="__health")
async def health() -> dict[str, Any]:
    """Reserved health probe: can we connect, log in and open the mailbox?"""
    missing = _missing_config()
    if missing is not None:
        return {"ok": False, "backend": "imap", "latency_ms": None, "detail": missing}
    started = time.monotonic()
    try:
        await asyncio.to_thread(_health_check)
        return {
            "ok": True,
            "backend": f"{HOST}:{_port()}",
            "latency_ms": round((time.monotonic() - started) * 1000, 1),
            "detail": None,
        }
    except Exception as e:
        return {"ok": False, "backend": f"{HOST}:{_port()}", "latency_ms": None, "detail": str(e)}


def run() -> None:
    mcp.run(transport="stdio")
