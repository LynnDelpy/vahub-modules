"""The GitHub module: what is waiting for you, as read-only tools.

It answers the questions a dashboard card asks, how many notifications are
unread, how many pull requests want your review, how many issues are assigned to
you, and lets the assistant look closer with a search. It never writes: every
tool is read-class, so it cannot open, close or comment on anything. It needs a
personal access token with read scopes (GITHUB_TOKEN); on GitHub Enterprise,
point GITHUB_API_URL at the instance.

As in every module here, the tool functions are thin wrappers over helpers the
tests call directly, and both the tools and the health probe report a backend
failure as a value instead of raising it, so one bad response never takes the
connection down.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

API_URL = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
TOKEN = (os.environ.get("GITHUB_TOKEN") or "").strip()
USER_AGENT = "vahub-mod-github/0.1 (+https://github.com/LynnDelpy/vahub-modules)"


def _timeout() -> float:
    try:
        return max(1.0, float(os.environ.get("GITHUB_TIMEOUT_S") or "12"))
    except ValueError:
        return 12.0


def _headers() -> dict[str, str]:
    headers = {
        "accept": "application/vnd.github+json",
        "x-github-api-version": "2022-11-28",
        "user-agent": USER_AGENT,
    }
    if TOKEN:
        headers["authorization"] = f"Bearer {TOKEN}"
    return headers


_http = httpx.AsyncClient(base_url=API_URL, timeout=_timeout(), headers=_headers())

mcp = FastMCP("github")


def _clamp(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(int(value), hi))
    except (TypeError, ValueError):
        return default


async def _get(path: str, params: dict[str, Any] | None = None) -> tuple[Any, str | None]:
    """Return (json, None) on success, or (None, message) on any failure. The
    message is safe to show: it names the status, never the token."""
    if not TOKEN:
        return None, "not configured: set GITHUB_TOKEN"
    try:
        response = await _http.get(path, params=params or {})
    except httpx.HTTPError as e:
        return None, f"cannot reach GitHub: {e}"
    if response.status_code == 401:
        return None, "GitHub rejected the token (401); check GITHUB_TOKEN"
    if response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0":
        return None, "GitHub rate limit reached; try again later"
    if response.status_code >= 400:
        return None, f"GitHub returned HTTP {response.status_code}"
    try:
        return response.json(), None
    except ValueError:
        return None, "GitHub returned a response that was not JSON"


# --------------------------------------------------------------------------
# pure shaping helpers (the tests call these directly)
# --------------------------------------------------------------------------
def summarize_notifications(payload: Any, limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in (payload if isinstance(payload, list) else [])[:limit]:
        if not isinstance(item, dict):
            continue
        subject = item.get("subject") if isinstance(item.get("subject"), dict) else {}
        repo = item.get("repository") if isinstance(item.get("repository"), dict) else {}
        out.append(
            {
                "repo": repo.get("full_name"),
                "title": subject.get("title"),
                "type": subject.get("type"),
                "reason": item.get("reason"),
                "updated_at": item.get("updated_at"),
            }
        )
    return out


def summarize_issues(payload: Any, limit: int) -> list[dict[str, Any]]:
    """Flatten a list of issues (from /issues) or search items (from
    /search/issues, which nests them under `items`) into the same shape."""
    items = payload.get("items") if isinstance(payload, dict) else payload
    out: list[dict[str, Any]] = []
    for item in (items if isinstance(items, list) else [])[:limit]:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "title": item.get("title"),
                "number": item.get("number"),
                "repository": _repo_from_url(item.get("repository_url")),
                "url": item.get("html_url"),
                "is_pull_request": "pull_request" in item,
                "updated_at": item.get("updated_at"),
            }
        )
    return out


def _repo_from_url(url: Any) -> str | None:
    # A search result carries repository_url like .../repos/owner/name; the
    # owner/name tail is the useful part, and this avoids a second request.
    if not isinstance(url, str) or "/repos/" not in url:
        return None
    return url.split("/repos/", 1)[1] or None


# --------------------------------------------------------------------------
# tools
# --------------------------------------------------------------------------
@mcp.tool()
async def summary() -> dict[str, Any]:
    """A one-call overview for the dashboard card: how many notifications are
    unread, how many pull requests want your review, how many issues are
    assigned to you, and the most recent few notifications."""
    notifications, error = await _get("/notifications", {"per_page": 30})
    if error is not None:
        return {"configured": bool(TOKEN), "error": error}
    reviews, _ = await _get("/search/issues", {"q": "is:open is:pr review-requested:@me", "per_page": 1})
    assigned, _ = await _get("/search/issues", {"q": "is:open is:issue assignee:@me", "per_page": 1})
    return {
        "configured": True,
        "notifications": len(notifications) if isinstance(notifications, list) else 0,
        "review_requests": reviews.get("total_count") if isinstance(reviews, dict) else None,
        "assigned_issues": assigned.get("total_count") if isinstance(assigned, dict) else None,
        "recent": summarize_notifications(notifications, 5),
    }


@mcp.tool()
async def notifications(limit: int = 20) -> dict[str, Any]:
    """Your unread notifications: repository, title, type and why you got it.

    limit: how many to return (1 to 50).
    """
    capped = _clamp(limit, 20, 1, 50)
    payload, error = await _get("/notifications", {"per_page": capped})
    if error is not None:
        return {"error": error}
    return {"notifications": summarize_notifications(payload, capped)}


@mcp.tool()
async def assigned_issues(limit: int = 20) -> dict[str, Any]:
    """Open issues assigned to you across every repository.

    limit: how many to return (1 to 50).
    """
    capped = _clamp(limit, 20, 1, 50)
    payload, error = await _get(
        "/search/issues", {"q": "is:open is:issue assignee:@me", "per_page": capped, "sort": "updated"}
    )
    if error is not None:
        return {"error": error}
    total = payload.get("total_count") if isinstance(payload, dict) else None
    return {"total": total, "issues": summarize_issues(payload, capped)}


@mcp.tool()
async def review_requests(limit: int = 20) -> dict[str, Any]:
    """Open pull requests that are waiting for your review.

    limit: how many to return (1 to 50).
    """
    capped = _clamp(limit, 20, 1, 50)
    payload, error = await _get(
        "/search/issues", {"q": "is:open is:pr review-requested:@me", "per_page": capped, "sort": "updated"}
    )
    if error is not None:
        return {"error": error}
    total = payload.get("total_count") if isinstance(payload, dict) else None
    return {"total": total, "pull_requests": summarize_issues(payload, capped)}


@mcp.tool()
async def search_issues(query: str, limit: int = 20) -> dict[str, Any]:
    """Search issues and pull requests with a GitHub search query.

    query: a GitHub search string, e.g. "repo:owner/name is:open label:bug".
    limit: how many to return (1 to 50).
    """
    capped = _clamp(limit, 20, 1, 50)
    payload, error = await _get("/search/issues", {"q": query, "per_page": capped})
    if error is not None:
        return {"error": error}
    total = payload.get("total_count") if isinstance(payload, dict) else None
    return {"query": query, "total": total, "results": summarize_issues(payload, capped)}


@mcp.tool(name="__health")
async def health() -> dict[str, Any]:
    """Reserved health probe: is the token accepted and the API reachable?"""
    if not TOKEN:
        return {"ok": False, "backend": "github", "latency_ms": None, "detail": "GITHUB_TOKEN is not set"}
    started = time.monotonic()
    try:
        response = await _http.get("/user")
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
