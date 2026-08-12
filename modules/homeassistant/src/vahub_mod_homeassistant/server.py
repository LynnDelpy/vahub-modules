"""Home Assistant module: lights, locks and sensor readings over HA's REST API.

Why there is no generic call_service tool
-----------------------------------------
Home Assistant's API is one endpoint, POST /api/services/{domain}/{service},
that can do everything the instance can do. Exposing that as a tool would be
less code and would make the module useless as a safety boundary: the policy
gate authorizes a call by tool name and argument values, so with a pass-through
the only thing it could constrain is the string "call_service". Rules like "the
model may dim the living room light but never touch a lock" would become
unwriteable, and every tool would collapse into one class. Narrow tools are the
point. If you need a service that is missing, add a named tool for it, give it
the class it deserves, and the gate keeps working.

The tool set is deliberately small: list, read, lights, locks. Unlocking is
`destructive` and normally sits behind a confirmation.

Config (environment, injected by the hub from module.yaml): HA_URL, HA_TOKEN or
HA_TOKEN_FILE, HA_VERIFY_SSL, HA_TIMEOUT_S.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

HA_URL = os.environ.get("HA_URL", "http://localhost:8123").rstrip("/")
HA_VERIFY_SSL = os.environ.get("HA_VERIFY_SSL", "true").strip().lower() not in ("false", "0", "no")

# Entity lists can be long and the hub truncates a tool result to a byte budget.
# Truncated JSON is worse than a short list, so the module caps its own output.
DEFAULT_ENTITY_LIMIT = 50
MAX_ENTITY_LIMIT = 200


def _read_secret(env_var: str, file_var: str) -> str:
    """Value from the environment, else from the file named by another variable.

    The file path is how production supplies a secret (a systemd credential, a
    Docker or Kubernetes secret) without it ever appearing in a unit file or in
    `ps`. Nothing here is logged, and the manifest lists HA_TOKEN under
    audit.redact so the hub scrubs it from audit records too.
    """
    value = os.environ.get(env_var, "").strip()
    if value:
        return value
    path = os.environ.get(file_var, "").strip()
    if path and os.path.exists(path):
        with open(path) as fh:
            return fh.read().strip()
    return ""


HA_TOKEN = _read_secret("HA_TOKEN", "HA_TOKEN_FILE")


def _timeout() -> float:
    try:
        return max(1.0, float(os.environ.get("HA_TIMEOUT_S", "10")))
    except ValueError:
        return 10.0


mcp = FastMCP("homeassistant")
_client = httpx.AsyncClient(
    base_url=HA_URL,
    headers={"Authorization": f"Bearer {HA_TOKEN}", "content-type": "application/json"},
    verify=HA_VERIFY_SSL,
    timeout=_timeout(),
)


def _clamp(value: Any, default: int, lo: int, hi: int) -> int:
    """Arguments arrive from a language model, so a string, a float or None are
    all realistic. None of them should raise out of a tool."""
    try:
        return max(lo, min(int(value), hi))
    except (TypeError, ValueError):
        return default


def summarize_states(payload: Any, domain: str | None, limit: int) -> list[dict[str, Any]]:
    """Reduce /api/states to entity_id plus state, filtered and bounded.

    Written as a plain function because it is where the parsing risk lives: the
    backend is not trusted to return the shape its documentation promises.
    """
    if not isinstance(payload, list):
        return []
    prefix = f"{domain.strip().rstrip('.')}." if domain else None
    out: list[dict[str, Any]] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        entity_id = entry.get("entity_id")
        if not isinstance(entity_id, str):
            continue
        if prefix and not entity_id.startswith(prefix):
            continue
        out.append({"entity_id": entity_id, "state": entry.get("state")})
        if len(out) >= limit:
            break
    return out


@mcp.tool()
async def list_entities(domain: str | None = None, limit: int = DEFAULT_ENTITY_LIMIT) -> dict[str, Any]:
    """List entities with their current state.

    domain: filter by Home Assistant domain, for example "light", "lock",
      "switch", "sensor". A real home has hundreds of entities, so filter
      whenever you know what you are looking for; use "sensor" for temperature,
      humidity and similar readings.
    limit: maximum number of entities to return (1 to 200).
    """
    capped = _clamp(limit, DEFAULT_ENTITY_LIMIT, 1, MAX_ENTITY_LIMIT)
    response = await _client.get("/api/states")
    response.raise_for_status()
    entities = summarize_states(response.json(), domain, capped)
    return {"domain": domain, "count": len(entities), "entities": entities}


@mcp.tool()
async def get_state(entity_id: str) -> dict[str, Any]:
    """Get one entity's state and attributes.

    entity_id: full id including the domain, for example "sensor.kitchen_temp".
    """
    response = await _client.get(f"/api/states/{entity_id}")
    if response.status_code == 404:
        return {"error": "not_found", "entity_id": entity_id}
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        return {"error": "unexpected_response", "entity_id": entity_id}
    attributes = data.get("attributes")
    return {
        "entity_id": data.get("entity_id", entity_id),
        "state": data.get("state"),
        "attributes": attributes if isinstance(attributes, dict) else {},
    }


async def _service(domain: str, service: str, data: dict[str, Any]) -> dict[str, Any]:
    response = await _client.post(f"/api/services/{domain}/{service}", json=data)
    response.raise_for_status()
    return {"ok": True, "entity_id": data.get("entity_id")}


@mcp.tool()
async def light_turn_on(entity_id: str, brightness_pct: int | None = None) -> dict[str, Any]:
    """Turn a light on, optionally at a brightness percentage.

    entity_id: a light entity, for example "light.living_room".
    brightness_pct: 1 to 100. Omit to use the light's previous brightness.
    """
    data: dict[str, Any] = {"entity_id": entity_id}
    if brightness_pct is not None:
        data["brightness_pct"] = _clamp(brightness_pct, 100, 1, 100)
    return await _service("light", "turn_on", data)


@mcp.tool()
async def light_turn_off(entity_id: str) -> dict[str, Any]:
    """Turn a light off.

    entity_id: a light entity, for example "light.living_room".
    """
    return await _service("light", "turn_off", {"entity_id": entity_id})


@mcp.tool()
async def lock_lock(entity_id: str) -> dict[str, Any]:
    """Lock a lock.

    entity_id: a lock entity, for example "lock.front_door".
    """
    return await _service("lock", "lock", {"entity_id": entity_id})


@mcp.tool()
async def lock_unlock(entity_id: str) -> dict[str, Any]:
    """Unlock a lock. Destructive: this opens a door.

    entity_id: a lock entity, for example "lock.front_door".
    """
    return await _service("lock", "unlock", {"entity_id": entity_id})


@mcp.tool(name="__health")
async def health() -> dict[str, Any]:
    """Reserved health probe: is Home Assistant reachable and is the token good?"""
    started = time.monotonic()
    if not HA_TOKEN:
        return {
            "ok": False,
            "backend": "homeassistant",
            "latency_ms": None,
            "detail": "no token configured (set HA_TOKEN or HA_TOKEN_FILE)",
        }
    try:
        response = await _client.get("/api/")
        ok = response.status_code == 200
        return {
            "ok": ok,
            "backend": "homeassistant",
            "latency_ms": round((time.monotonic() - started) * 1000, 1),
            # 401 here means the token, not the network, so say which it is.
            "detail": None if ok else f"status {response.status_code}",
        }
    except Exception as e:
        # A probe reports failures, it never raises them: the hub marks the
        # module degraded, and an exception here would look like a crash.
        return {"ok": False, "backend": "homeassistant", "latency_ms": None, "detail": str(e)}


def run() -> None:
    mcp.run(transport="stdio")
