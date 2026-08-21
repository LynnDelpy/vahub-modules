"""The homelab module: are your self-hosted services up?

It answers the dashboard card's question, which of my services are reachable
right now, by probing a list of targets you configure: an HTTP URL (up when it
answers with an acceptable status) or a host and port (up when a TCP connection
opens). It never sends a request body, never follows a redirect, and never does
anything but a plain GET or connect, so it cannot act on a service, only observe
whether it answers.

All probes for one call run concurrently. As in every module here, the target
parsing is a helper the tests call directly, and a probe that fails is reported
as ``ok: false`` with a reason, never raised.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

HOMELAB_TARGETS = os.environ.get("HOMELAB_TARGETS") or ""
USER_AGENT = "vahub-mod-homelab/0.1 (+https://github.com/LynnDelpy/vahub-modules)"
MAX_TARGETS = 100  # a bounded list, so a huge config cannot fan out without limit

mcp = FastMCP("homelab")


def _timeout() -> float:
    try:
        return max(1.0, float(os.environ.get("HOMELAB_TIMEOUT_S") or "5"))
    except ValueError:
        return 5.0


def _verify_ssl() -> bool:
    return (os.environ.get("HOMELAB_VERIFY_SSL") or "true").strip().lower() not in ("false", "0", "no", "off")


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# pure helpers (the tests call these directly)
# --------------------------------------------------------------------------
def parse_targets(raw: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Turn the HOMELAB_TARGETS JSON into validated targets and a list of
    human-readable problems. A malformed entry becomes a problem, not an
    exception, and never stops the valid targets from being checked.

    Each entry is an object with a ``name`` and either a ``url`` (an HTTP check,
    optional ``expect_status``) or a ``host`` and ``port`` (a TCP check)."""
    raw = (raw or "").strip()
    if not raw:
        return [], []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        return [], [f"HOMELAB_TARGETS is not valid JSON: {e}"]
    if not isinstance(data, list):
        return [], ["HOMELAB_TARGETS must be a JSON array of targets"]

    targets: list[dict[str, Any]] = []
    problems: list[str] = []
    for index, entry in enumerate(data[:MAX_TARGETS]):
        if not isinstance(entry, dict):
            problems.append(f"target {index}: not an object")
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            problems.append(f"target {index}: missing 'name'")
            continue
        if entry.get("url"):
            targets.append(
                {
                    "name": name,
                    "kind": "http",
                    "url": str(entry["url"]),
                    "expect_status": _int_or_none(entry.get("expect_status")),
                }
            )
        elif entry.get("host") and entry.get("port") is not None:
            port = _int_or_none(entry.get("port"))
            if port is None or not (1 <= port <= 65535):
                problems.append(f"target {name!r}: invalid port {entry.get('port')!r}")
                continue
            targets.append({"name": name, "kind": "tcp", "host": str(entry["host"]), "port": port})
        else:
            problems.append(f"target {name!r}: needs 'url', or 'host' and 'port'")
    if len(data) > MAX_TARGETS:
        problems.append(f"only the first {MAX_TARGETS} targets are checked ({len(data)} given)")
    return targets, problems


def http_ok(status: int, expect: int | None) -> bool:
    """Whether an HTTP status counts as up: exactly ``expect`` if one was given,
    otherwise any 2xx or 3xx."""
    if expect is not None:
        return status == expect
    return 200 <= status < 400


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    up = sum(1 for r in results if r["ok"])
    return {"up": up, "down": len(results) - up, "total": len(results), "targets": results}


def _result(target: dict[str, Any], ok: bool, detail: str | None, started: float) -> dict[str, Any]:
    return {
        "name": target["name"],
        "kind": target["kind"],
        "ok": ok,
        "detail": detail,
        "latency_ms": round((time.monotonic() - started) * 1000, 1),
    }


# --------------------------------------------------------------------------
# probes
# --------------------------------------------------------------------------
async def _probe_http(client: httpx.AsyncClient, target: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    try:
        response = await client.get(target["url"])
    except Exception as e:  # an unreachable service is a value, never a crash
        return _result(target, False, str(e), started)
    ok = http_ok(response.status_code, target.get("expect_status"))
    return _result(target, ok, None if ok else f"HTTP {response.status_code}", started)


async def _probe_tcp(target: dict[str, Any], timeout: float) -> dict[str, Any]:
    started = time.monotonic()
    try:
        opening = asyncio.open_connection(target["host"], target["port"])
        _reader, writer = await asyncio.wait_for(opening, timeout=timeout)
    except TimeoutError:
        return _result(target, False, "timed out", started)
    except OSError as e:
        return _result(target, False, str(e) or "connection refused", started)
    except Exception as e:
        return _result(target, False, str(e), started)
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()
    return _result(target, True, None, started)


async def _probe_all(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    timeout = _timeout()
    async with httpx.AsyncClient(
        verify=_verify_ssl(), timeout=timeout, follow_redirects=False, headers={"user-agent": USER_AGENT}
    ) as client:
        probes = [
            _probe_http(client, t) if t["kind"] == "http" else _probe_tcp(t, timeout) for t in targets
        ]
        return list(await asyncio.gather(*probes))


# --------------------------------------------------------------------------
# tools
# --------------------------------------------------------------------------
@mcp.tool()
async def summary() -> dict[str, Any]:
    """Up/down counts and per-target status for the dashboard card."""
    if not HOMELAB_TARGETS.strip():
        return {"configured": False, "error": "not configured: set HOMELAB_TARGETS"}
    targets, problems = parse_targets(HOMELAB_TARGETS)
    if not targets:
        return {"configured": True, "error": "no usable targets", "problems": problems}
    out = summarize(await _probe_all(targets))
    out["configured"] = True
    if problems:
        out["problems"] = problems
    return out


@mcp.tool()
async def check(name: str | None = None) -> dict[str, Any]:
    """Probe every target now, or just the one named.

    name: the exact name of a single target to check. Omit to check them all.
    """
    if not HOMELAB_TARGETS.strip():
        return {"error": "not configured: set HOMELAB_TARGETS"}
    targets, problems = parse_targets(HOMELAB_TARGETS)
    if name:
        wanted = name.strip().lower()
        targets = [t for t in targets if t["name"].lower() == wanted]
        if not targets:
            return {"error": f"no target named {name!r}"}
    if not targets:
        return {"error": "no usable targets", "problems": problems}
    out = summarize(await _probe_all(targets))
    if problems and not name:
        out["problems"] = problems
    return out


@mcp.tool(name="__health")
async def health() -> dict[str, Any]:
    """Reserved health probe: is the target list present and parseable?

    This reports on the module, not on the services: a service being down is the
    thing the tools report, so it never makes the module itself unhealthy."""
    if not HOMELAB_TARGETS.strip():
        return {"ok": False, "backend": "homelab", "latency_ms": None, "detail": "HOMELAB_TARGETS is not set"}
    targets, problems = parse_targets(HOMELAB_TARGETS)
    ok = bool(targets)
    detail = None if ok else (problems[0] if problems else "no usable targets")
    return {"ok": ok, "backend": f"{len(targets)} target(s)", "latency_ms": None, "detail": detail}


def run() -> None:
    mcp.run(transport="stdio")
