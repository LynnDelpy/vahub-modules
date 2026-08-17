"""The GitLab module: what needs your attention, as read-only tools.

It answers the dashboard card's questions, how many to-dos are pending, how many
merge requests are assigned to you, how many issues, and lets the assistant list
them. Every tool is read-class: it never approves, merges or closes anything. It
needs a personal access token with the read_api scope (GITLAB_TOKEN); on a
self-managed instance, point GITLAB_API_URL at it.

As in every module here, the tool functions are thin wrappers over helpers the
tests call directly, and both the tools and the health probe report a backend
failure as a value instead of raising it.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

API_URL = os.environ.get("GITLAB_API_URL", "https://gitlab.com/api/v4").rstrip("/")
TOKEN = (os.environ.get("GITLAB_TOKEN") or "").strip()
USER_AGENT = "vahub-mod-gitlab/0.1 (+https://github.com/LynnDelpy/vahub-modules)"


def _timeout() -> float:
    try:
        return max(1.0, float(os.environ.get("GITLAB_TIMEOUT_S") or "12"))
    except ValueError:
        return 12.0


def _headers() -> dict[str, str]:
    headers = {"accept": "application/json", "user-agent": USER_AGENT}
    if TOKEN:
        headers["authorization"] = f"Bearer {TOKEN}"
    return headers


_http = httpx.AsyncClient(base_url=API_URL, timeout=_timeout(), headers=_headers())

mcp = FastMCP("gitlab")


def _clamp(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(int(value), hi))
    except (TypeError, ValueError):
        return default


def _total(response: httpx.Response, data: Any) -> int | None:
    """The count of matching records, from GitLab's X-Total header. When the
    header is absent (GitLab omits it for very large or expensive result sets)
    the true total is unknown, so this returns None rather than the page length,
    which for a per_page=1 count query would misreport a large set as "1"."""
    header = response.headers.get("x-total")
    if header and header.isdigit():
        return int(header)
    return None


async def _get(path: str, params: dict[str, Any] | None = None) -> tuple[Any, int | None, str | None]:
    """Return (json, total, None) on success, or (None, None, message) on failure.
    The message is safe to show: it names the status, never the token."""
    if not TOKEN:
        return None, None, "not configured: set GITLAB_TOKEN"
    try:
        response = await _http.get(path, params=params or {})
    except httpx.HTTPError as e:
        return None, None, f"cannot reach GitLab: {e}"
    if response.status_code == 401:
        return None, None, "GitLab rejected the token (401); check GITLAB_TOKEN"
    if response.status_code >= 400:
        return None, None, f"GitLab returned HTTP {response.status_code}"
    try:
        data = response.json()
    except ValueError:
        return None, None, "GitLab returned a response that was not JSON"
    return data, _total(response, data), None


# --------------------------------------------------------------------------
# pure shaping helpers (the tests call these directly)
# --------------------------------------------------------------------------
def _project_name(item: dict[str, Any]) -> Any:
    project = item.get("project")
    if isinstance(project, dict):
        return project.get("name_with_namespace") or project.get("path_with_namespace")
    references = item.get("references")
    if isinstance(references, dict):
        return references.get("full")
    return None


def summarize_todos(payload: Any, limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in (payload if isinstance(payload, list) else [])[:limit]:
        if not isinstance(item, dict):
            continue
        target = item.get("target") if isinstance(item.get("target"), dict) else {}
        out.append(
            {
                "type": item.get("target_type"),
                "title": target.get("title") or item.get("body"),
                "action": item.get("action_name"),
                "project": _project_name(item),
                "url": item.get("target_url"),
            }
        )
    return out


def summarize_items(payload: Any, limit: int) -> list[dict[str, Any]]:
    """Shape a list of merge requests or issues into a common form."""
    out: list[dict[str, Any]] = []
    for item in (payload if isinstance(payload, list) else [])[:limit]:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "title": item.get("title"),
                "reference": item.get("reference"),
                "project": _project_name(item),
                "url": item.get("web_url"),
                "updated_at": item.get("updated_at"),
            }
        )
    return out


# --------------------------------------------------------------------------
# tools
# --------------------------------------------------------------------------
@mcp.tool()
async def summary() -> dict[str, Any]:
    """A one-call overview for the dashboard card: how many to-dos are pending,
    how many merge requests and issues are assigned to you, and the most recent
    few to-dos."""
    todos_data, todos_total, error = await _get("/todos", {"state": "pending", "per_page": 20})
    if error is not None:
        return {"configured": bool(TOKEN), "error": error}
    _, mrs_total, _ = await _get(
        "/merge_requests", {"scope": "assigned_to_me", "state": "opened", "per_page": 1}
    )
    _, issues_total, _ = await _get("/issues", {"scope": "assigned_to_me", "state": "opened", "per_page": 1})
    return {
        "configured": True,
        "todos": todos_total,
        "assigned_merge_requests": mrs_total,
        "assigned_issues": issues_total,
        "recent": summarize_todos(todos_data, 5),
    }


@mcp.tool()
async def todos(limit: int = 20) -> dict[str, Any]:
    """Your pending to-dos: what GitLab thinks needs your attention.

    limit: how many to return (1 to 50).
    """
    capped = _clamp(limit, 20, 1, 50)
    data, total, error = await _get("/todos", {"state": "pending", "per_page": capped})
    if error is not None:
        return {"error": error}
    return {"total": total, "todos": summarize_todos(data, capped)}


@mcp.tool()
async def assigned_merge_requests(limit: int = 20) -> dict[str, Any]:
    """Open merge requests assigned to you.

    limit: how many to return (1 to 50).
    """
    capped = _clamp(limit, 20, 1, 50)
    data, total, error = await _get(
        "/merge_requests",
        {"scope": "assigned_to_me", "state": "opened", "order_by": "updated_at", "per_page": capped},
    )
    if error is not None:
        return {"error": error}
    return {"total": total, "merge_requests": summarize_items(data, capped)}


@mcp.tool()
async def assigned_issues(limit: int = 20) -> dict[str, Any]:
    """Open issues assigned to you.

    limit: how many to return (1 to 50).
    """
    capped = _clamp(limit, 20, 1, 50)
    data, total, error = await _get(
        "/issues",
        {"scope": "assigned_to_me", "state": "opened", "order_by": "updated_at", "per_page": capped},
    )
    if error is not None:
        return {"error": error}
    return {"total": total, "issues": summarize_items(data, capped)}


@mcp.tool(name="__health")
async def health() -> dict[str, Any]:
    """Reserved health probe: is the token accepted and the API reachable?"""
    if not TOKEN:
        return {"ok": False, "backend": "gitlab", "latency_ms": None, "detail": "GITLAB_TOKEN is not set"}
    started = time.monotonic()
    try:
        # Bound the probe below the manifest's health.timeout_s (8s), so a backend
        # that silently drops the connection cannot make __health miss its window.
        response = await _http.get("/user", timeout=min(_timeout(), 6.0))
        ok = response.status_code == 200
        return {
            "ok": ok,
            "backend": API_URL,
            "latency_ms": round((time.monotonic() - started) * 1000, 1),
            "detail": None if ok else f"status {response.status_code}",
        }
    except Exception as e:
        return {"ok": False, "backend": API_URL, "latency_ms": None, "detail": str(e)}


def run() -> None:
    mcp.run(transport="stdio")
