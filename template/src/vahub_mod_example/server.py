"""Template module: copy this directory and make it yours.

A module is an ordinary program that speaks MCP over stdin and stdout. The hub
spawns it, talks to it through a pipe, and can kill it. It is never imported, so
nothing here can reach into the hub, and the hub's environment is not visible:
only the keys declared in module.yaml are passed in.

The one shipped tool reverses a string, which is enough to prove the whole path
works (spawn, handshake, catalog, policy gate, call, result) before you replace
it with something that talks to a real backend.
"""

from __future__ import annotations

import os
import time
from typing import Any

from mcp.server.fastmcp import FastMCP

# Declare every key you read here in module.yaml, or it will not be passed in.
GREETING = os.environ.get("EXAMPLE_GREETING", "hello")

mcp = FastMCP("example")


def shout(text: str) -> str:
    """The logic lives in a plain function so the test can call it without the
    MCP machinery. Keep this habit: it makes tools trivial to test."""
    return f"{GREETING} {text[::-1]}"


@mcp.tool()
def reverse(text: str) -> str:
    """Return the text reversed, with a greeting in front.

    text: whatever you want reversed.

    Write these docstrings for the language model. It picks a tool from the
    first line and fills the arguments from the lines below, so describe what
    the tool actually does. An inflated description is a bug, not marketing.
    """
    return shout(text)


# __health is reserved by the module contract. The hub calls it on a timer to
# distinguish "the process is up" from "the backend answers", and it is never
# offered to the model. Return these four keys. If your module talks to
# something, measure a real request here; report a failure, do not raise it.
@mcp.tool(name="__health")
def health() -> dict[str, Any]:
    """Reserved health probe."""
    started = time.monotonic()
    return {
        "ok": True,
        "backend": "none",
        "latency_ms": round((time.monotonic() - started) * 1000, 1),
        "detail": None,
    }


def run() -> None:
    mcp.run(transport="stdio")
