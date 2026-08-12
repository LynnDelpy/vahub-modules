"""Push notifications, through ntfy or Pushover.

One tool, send_push. It is `write`, not `read`: a notification leaves the house,
reaches a phone, and cannot be recalled, so it belongs behind a rule that says
which titles and priorities are acceptable.

Two decisions:

* Secrets can come from a file (PUSHOVER_TOKEN_FILE and friends) as well as from
  the environment, so production can hand them over as a systemd credential or a
  Docker secret without them appearing in a unit file or in `ps`.
* A missing topic or token is reported by the health probe and returned as
  {"ok": false, ...} by the tool, rather than raised. An unconfigured module
  should show up as degraded on the status page, not as a crash loop.

Config: NOTIFY_BACKEND, plus the keys of whichever backend you chose.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

BACKEND = os.environ.get("NOTIFY_BACKEND", "ntfy").strip().lower()

NTFY_URL = os.environ.get("NTFY_URL", "https://ntfy.sh").rstrip("/")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()

PUSHOVER_API = "https://api.pushover.net/1"

# ntfy uses 1..5; Pushover uses -2..1 (its emergency level 2 is deliberately not
# reachable from here, since it retries until a human acknowledges it).
NTFY_PRIORITY = {"min": 1, "low": 2, "default": 3, "high": 4, "urgent": 5}
PUSHOVER_PRIORITY = {"min": -2, "low": -1, "default": 0, "high": 1, "urgent": 1}

MAX_TITLE = 120
MAX_MESSAGE = 1000


def _read_secret(env_var: str, file_var: str) -> str:
    value = os.environ.get(env_var, "").strip()
    if value:
        return value
    path = os.environ.get(file_var, "").strip()
    if path and os.path.exists(path):
        with open(path) as fh:
            return fh.read().strip()
    return ""


NTFY_TOKEN = _read_secret("NTFY_TOKEN", "NTFY_TOKEN_FILE")
PUSHOVER_TOKEN = _read_secret("PUSHOVER_TOKEN", "PUSHOVER_TOKEN_FILE")
PUSHOVER_USER = _read_secret("PUSHOVER_USER", "PUSHOVER_USER_FILE")

mcp = FastMCP("notify")
_client = httpx.AsyncClient(timeout=10.0, headers={"user-agent": "vahub-mod-notify/0.1"})


def normalize_priority(value: Any) -> str:
    """Unknown or oddly typed priorities become "default". The value comes from
    a model, and sending at the wrong urgency beats not sending at all."""
    if isinstance(value, str) and value.strip().lower() in NTFY_PRIORITY:
        return value.strip().lower()
    return "default"


def clip(text: Any, limit: int) -> str:
    """Push services truncate long fields themselves, in their own ways. Doing
    it here keeps what the audit log records identical to what was sent."""
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 3] + "..."


async def _send_ntfy(title: str, message: str, priority: str, tags: str | None) -> dict[str, Any]:
    if not NTFY_TOPIC:
        return {"ok": False, "backend": "ntfy", "detail": "NTFY_TOPIC not configured"}
    # ntfy's other publishing style puts the title and tags in HTTP headers,
    # which are latin-1 on the wire: an umlaut in a title would fail to encode
    # before the request was even sent. The JSON form is UTF-8 throughout.
    body: dict[str, Any] = {
        "topic": NTFY_TOPIC,
        "title": title,
        "message": message,
        "priority": NTFY_PRIORITY[priority],
    }
    if tags:
        body["tags"] = [tag.strip() for tag in tags.split(",") if tag.strip()]
    headers = {}
    if NTFY_TOKEN:  # only needed for a protected topic on a self-hosted server
        headers["Authorization"] = f"Bearer {NTFY_TOKEN}"
    response = await _client.post(NTFY_URL, json=body, headers=headers)
    ok = response.status_code < 300
    return {
        "ok": ok,
        "backend": "ntfy",
        "status": response.status_code,
        "detail": None if ok else response.text[:200],
    }


async def _send_pushover(title: str, message: str, priority: str, tags: str | None) -> dict[str, Any]:
    if not (PUSHOVER_TOKEN and PUSHOVER_USER):
        return {"ok": False, "backend": "pushover", "detail": "PUSHOVER_TOKEN/PUSHOVER_USER not configured"}
    response = await _client.post(
        f"{PUSHOVER_API}/messages.json",
        data={
            "token": PUSHOVER_TOKEN,
            "user": PUSHOVER_USER,
            "title": title,
            "message": message,
            "priority": PUSHOVER_PRIORITY[priority],
        },
    )
    ok = response.status_code == 200
    return {
        "ok": ok,
        "backend": "pushover",
        "status": response.status_code,
        "detail": None if ok else response.text[:200],
    }


@mcp.tool()
async def send_push(
    title: str,
    message: str,
    priority: str = "default",
    tags: str | None = None,
) -> dict[str, Any]:
    """Send a push notification to the configured device or topic.

    title: short headline shown in the notification.
    message: the body text.
    priority: one of "min", "low", "default", "high", "urgent".
    tags: optional and backend specific. ntfy reads these as emoji short codes
      such as "warning,house"; Pushover ignores them.
    """
    title = clip(title, MAX_TITLE)
    message = clip(message, MAX_MESSAGE)
    level = normalize_priority(priority)
    if BACKEND == "pushover":
        return await _send_pushover(title, message, level, tags)
    return await _send_ntfy(title, message, level, tags)


@mcp.tool(name="__health")
async def health() -> dict[str, Any]:
    """Reserved health probe: is the chosen backend configured and reachable?

    The probe never sends a notification. It validates credentials (Pushover) or
    asks about the topic (ntfy), because a health check that buzzes a phone
    every thirty seconds would not survive its first night.
    """
    started = time.monotonic()
    try:
        if BACKEND == "pushover":
            if not (PUSHOVER_TOKEN and PUSHOVER_USER):
                return {
                    "ok": False,
                    "backend": "pushover",
                    "latency_ms": None,
                    "detail": "PUSHOVER_TOKEN/PUSHOVER_USER not configured",
                }
            response = await _client.post(
                f"{PUSHOVER_API}/users/validate.json",
                data={"token": PUSHOVER_TOKEN, "user": PUSHOVER_USER},
            )
            ok = response.status_code == 200
        else:
            if not NTFY_TOPIC:
                return {
                    "ok": False,
                    "backend": "ntfy",
                    "latency_ms": None,
                    "detail": "NTFY_TOPIC not configured",
                }
            response = await _client.head(f"{NTFY_URL}/{NTFY_TOPIC}")
            # 4xx on a HEAD to a topic is normal for some deployments; only a
            # server error or a refused connection means the backend is down.
            ok = response.status_code < 500
        return {
            "ok": ok,
            "backend": BACKEND,
            "latency_ms": round((time.monotonic() - started) * 1000, 1),
            "detail": None if ok else f"status {response.status_code}",
        }
    except Exception as e:
        # A probe reports failures, it never raises them: the hub marks the
        # module degraded, and an exception here would look like a crash.
        return {"ok": False, "backend": BACKEND, "latency_ms": None, "detail": str(e)}


def run() -> None:
    mcp.run(transport="stdio")
