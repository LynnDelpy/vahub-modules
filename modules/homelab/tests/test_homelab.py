"""Unit tests for the homelab module.

The target parsing and the up/down logic are pure and tested directly. The
probes are exercised against loopback: a real listening socket and a local HTTP
server, so nothing here touches the network.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from vahub_mod_homelab import server


def test_parse_targets_reads_http_and_tcp_entries() -> None:
    raw = json.dumps(
        [
            {"name": "Web", "url": "https://web.home", "expect_status": 200},
            {"name": "Router", "url": "http://10.0.0.1"},
            {"name": "SSH", "host": "10.0.0.2", "port": 22},
        ]
    )
    targets, problems = server.parse_targets(raw)
    assert problems == []
    assert targets[0] == {"name": "Web", "kind": "http", "url": "https://web.home", "expect_status": 200}
    assert targets[1]["expect_status"] is None
    assert targets[2] == {"name": "SSH", "kind": "tcp", "host": "10.0.0.2", "port": 22}


def test_parse_targets_reports_malformed_entries_without_dropping_valid_ones() -> None:
    raw = json.dumps(
        [
            {"url": "https://x"},  # no name
            {"name": "NoTarget"},  # neither url nor host/port
            {"name": "BadPort", "host": "h", "port": 99999},
            {"name": "Good", "host": "h", "port": 80},
        ]
    )
    targets, problems = server.parse_targets(raw)
    assert [t["name"] for t in targets] == ["Good"]
    assert len(problems) == 3


def test_parse_targets_handles_bad_json_and_non_lists() -> None:
    assert server.parse_targets("not json")[1]
    assert server.parse_targets('{"name": "x"}')[1] == ["HOMELAB_TARGETS must be a JSON array of targets"]
    assert server.parse_targets("") == ([], [])


def test_http_ok_logic() -> None:
    assert server.http_ok(200, None) is True
    assert server.http_ok(301, None) is True
    assert server.http_ok(404, None) is False
    assert server.http_ok(500, 500) is True
    assert server.http_ok(200, 204) is False


def test_summarize_counts_up_and_down() -> None:
    results = [{"ok": True}, {"ok": False}, {"ok": True}]
    out = server.summarize(results)
    assert out["up"] == 2 and out["down"] == 1 and out["total"] == 3


def test_tcp_probe_up_on_a_listening_socket_and_down_on_a_closed_port() -> None:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    target = {"name": "s", "kind": "tcp", "host": "127.0.0.1", "port": port}
    try:
        up = asyncio.run(server._probe_tcp(target, 2.0))
        assert up["ok"] is True and up["latency_ms"] is not None
    finally:
        listener.close()
    down = asyncio.run(server._probe_tcp(target, 1.0))
    assert down["ok"] is False


def _serve_200() -> tuple[HTTPServer, int]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args: object) -> None:
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def test_summary_probes_a_live_http_target(monkeypatch) -> None:
    httpd, port = _serve_200()
    try:
        monkeypatch.setattr(server, "HOMELAB_TARGETS", json.dumps([{"name": "web", "url": f"http://127.0.0.1:{port}/"}]))
        out = asyncio.run(server.summary())
        assert out["configured"] is True and out["up"] == 1
        assert out["targets"][0]["ok"] is True

        monkeypatch.setattr(
            server,
            "HOMELAB_TARGETS",
            json.dumps([{"name": "web", "url": f"http://127.0.0.1:{port}/", "expect_status": 500}]),
        )
        mismatch = asyncio.run(server.summary())
        assert mismatch["down"] == 1 and "HTTP 200" in mismatch["targets"][0]["detail"]
    finally:
        httpd.shutdown()


def test_tools_report_missing_configuration(monkeypatch) -> None:
    monkeypatch.setattr(server, "HOMELAB_TARGETS", "")
    result = asyncio.run(server.summary())
    assert result["configured"] is False and "HOMELAB_TARGETS" in result["error"]
    health = asyncio.run(server.health())
    assert health["ok"] is False and "HOMELAB_TARGETS" in health["detail"]
