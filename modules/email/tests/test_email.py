"""Unit tests for the email module's header parsing and configuration guard.

The IMAP calls need a server, but the header parsing (including MIME-encoded
words) and the "not configured" behaviour are pure and worth testing here.
"""

from __future__ import annotations

import asyncio

from vahub_mod_email import server


def test_decode_mime_header_decodes_encoded_words() -> None:
    # "=?utf-8?b?w4RwZmVs?=" is base64 for "Äpfel".
    assert server.decode_mime_header("=?utf-8?b?w4RwZmVs?=") == "Äpfel"
    assert server.decode_mime_header("plain subject") == "plain subject"
    assert server.decode_mime_header(None) == ""


def test_header_summary_pulls_the_card_fields() -> None:
    raw = b"From: Lynn <lynn@example.com>\r\nSubject: Hello\r\nDate: Mon, 16 Aug 2026 10:00:00 +0000\r\n\r\n"
    out = server.header_summary(raw)
    assert out == {
        "from": "Lynn <lynn@example.com>",
        "subject": "Hello",
        "date": "Mon, 16 Aug 2026 10:00:00 +0000",
    }


def test_extract_header_bytes_picks_the_tuple_part() -> None:
    fetched = [(b"1 (BODY[HEADER] {12}", b"Subject: hi\r\n"), b")"]
    assert server._extract_header_bytes(fetched) == b"Subject: hi\r\n"
    assert server._extract_header_bytes([b"just a flag"]) == b""


def test_port_and_ssl_defaults(monkeypatch) -> None:
    monkeypatch.delenv("EMAIL_PORT", raising=False)
    monkeypatch.setenv("EMAIL_SSL", "true")
    assert server._use_ssl() is True and server._port() == 993
    monkeypatch.setenv("EMAIL_SSL", "false")
    assert server._use_ssl() is False and server._port() == 143


def test_clamp_keeps_the_limit_in_range() -> None:
    assert server._clamp(999, 20, 1, 50) == 50
    assert server._clamp(0, 20, 1, 50) == 1
    assert server._clamp("x", 20, 1, 50) == 20


def test_summary_reports_missing_configuration(monkeypatch) -> None:
    monkeypatch.setattr(server, "HOST", "")
    monkeypatch.setattr(server, "USERNAME", "")
    monkeypatch.setattr(server, "PASSWORD", "")
    result = asyncio.run(server.summary())
    assert result["configured"] is False
    for key in ("EMAIL_HOST", "EMAIL_USERNAME", "EMAIL_PASSWORD"):
        assert key in result["error"]


def test_health_without_configuration_is_a_clean_not_ok(monkeypatch) -> None:
    monkeypatch.setattr(server, "HOST", "")
    health = asyncio.run(server.health())
    assert health["ok"] is False and "EMAIL_HOST" in health["detail"]


def test_imap_quote_escapes_and_strips() -> None:
    assert server._imap_quote("hello") == '"hello"'
    assert server._imap_quote('a"b') == '"a\\"b"'  # embedded quote escaped
    assert server._imap_quote("a\\b") == '"a\\\\b"'  # embedded backslash escaped
    stripped = server._imap_quote("a\rb\nc")
    assert "\r" not in stripped and "\n" not in stripped  # no command injection
