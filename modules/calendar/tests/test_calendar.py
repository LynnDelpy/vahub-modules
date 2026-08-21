"""Unit tests for the calendar module's parsing helpers.

The tools are thin wrappers over these and over the network, so parsing an ICS
feed, expanding recurrences and the "not configured" behaviour are what is worth
testing without a live feed.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from icalendar import Calendar

from vahub_mod_calendar import server

UTC = ZoneInfo("UTC")

SAMPLE = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//test//EN
X-WR-CALNAME:Test Cal
BEGIN:VEVENT
UID:1@test
DTSTART:20260101T090000Z
DTEND:20260101T100000Z
SUMMARY:Timed meeting
LOCATION:Room A
END:VEVENT
BEGIN:VEVENT
UID:2@test
DTSTART;VALUE=DATE:20260102
DTEND;VALUE=DATE:20260103
SUMMARY:All day thing
END:VEVENT
BEGIN:VEVENT
UID:3@test
DTSTART:20260105T120000Z
DTEND:20260105T123000Z
RRULE:FREQ=DAILY;COUNT=3
SUMMARY:Daily standup
END:VEVENT
END:VCALENDAR
"""


def _events(window_start=datetime(2026, 1, 1, tzinfo=UTC), window_end=datetime(2026, 1, 10, tzinfo=UTC)):
    cal = Calendar.from_ical(SAMPLE)
    return server.expand_events(cal, window_start, window_end, UTC, server.calendar_name(cal, "https://h/f.ics"))


def test_split_urls_accepts_whitespace_comma_and_newlines() -> None:
    raw = "https://a/x.ics, https://b/y.ics\nhttps://c/z.ics"
    assert server.split_urls(raw) == ["https://a/x.ics", "https://b/y.ics", "https://c/z.ics"]
    assert server.split_urls("   ") == []


def test_calendar_name_prefers_the_declared_name_then_the_host() -> None:
    named = Calendar.from_ical(SAMPLE)
    assert server.calendar_name(named, "https://host/feed.ics") == "Test Cal"
    plain = Calendar.from_ical(b"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//t//t//EN\nEND:VCALENDAR\n")
    assert server.calendar_name(plain, "https://host.example/feed.ics") == "host.example"


def test_recurring_events_are_expanded_within_the_window() -> None:
    events = _events()
    by_summary = Counter(e["summary"] for e in events)
    assert by_summary["Timed meeting"] == 1
    assert by_summary["All day thing"] == 1
    assert by_summary["Daily standup"] == 3  # COUNT=3, all inside the window
    assert len(events) == 5


def test_a_narrow_window_drops_out_of_range_occurrences() -> None:
    # Only Jan 1 to Jan 3: the timed meeting and the all-day event, no standups.
    events = _events(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 3, tzinfo=UTC))
    assert {e["summary"] for e in events} == {"Timed meeting", "All day thing"}


def test_all_day_and_timed_events_serialize_distinctly() -> None:
    events = {e["summary"]: e for e in _events()}
    timed = events["Timed meeting"]
    assert timed["all_day"] is False
    assert timed["start"] == "2026-01-01T09:00:00+00:00"
    assert timed["location"] == "Room A"
    all_day = events["All day thing"]
    assert all_day["all_day"] is True
    assert all_day["start"] == "2026-01-02T00:00:00+00:00"
    assert all_day["location"] is None


def test_naive_datetimes_are_read_in_the_configured_zone() -> None:
    zurich = ZoneInfo("Europe/Zurich")
    raw = (
        b"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//t//t//EN\n"
        b"BEGIN:VEVENT\nUID:n@test\nDTSTART:20260601T140000\nDTEND:20260601T150000\n"
        b"SUMMARY:Local\nEND:VEVENT\nEND:VCALENDAR\n"
    )
    cal = Calendar.from_ical(raw)
    start = datetime(2026, 6, 1, tzinfo=zurich)
    end = datetime(2026, 6, 2, tzinfo=zurich)
    events = server.expand_events(cal, start, end, zurich, "z")
    assert events[0]["start"] == "2026-06-01T14:00:00+02:00"


def test_public_strips_the_internal_sort_key() -> None:
    event = server.serialize_event(
        Calendar.from_ical(SAMPLE).walk("VEVENT")[0], UTC, "Test Cal"
    )
    assert "_sort" in event
    assert "_sort" not in server.public(event)


def test_matches_looks_across_title_location_and_calendar() -> None:
    events = {e["summary"]: e for e in _events()}
    assert server._matches(events["Timed meeting"], "room a") is True
    assert server._matches(events["Timed meeting"], "nonsense") is False


def test_tools_report_missing_configuration(monkeypatch) -> None:
    monkeypatch.setattr(server, "ICS_URLS", "")
    result = asyncio.run(server.summary())
    assert result["configured"] is False and "CALENDAR_ICS_URLS" in result["error"]
    health = asyncio.run(server.health())
    assert health["ok"] is False and "CALENDAR_ICS_URLS" in health["detail"]


class _FakeStream:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def __aenter__(self) -> _FakeStream:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    def raise_for_status(self) -> None:
        pass

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk


def test_fetch_stops_reading_past_the_size_cap(monkeypatch) -> None:
    monkeypatch.setattr(server, "MAX_FEED_BYTES", 10)
    monkeypatch.setattr(server._http, "stream", lambda *a, **k: _FakeStream([b"x" * 8, b"y" * 8]))
    with pytest.raises(ValueError, match="larger than"):
        asyncio.run(server._fetch("https://feed.test/big.ics"))


def test_health_is_bounded_when_a_feed_is_slow(monkeypatch) -> None:
    monkeypatch.setattr(server, "ICS_URLS", "https://slow.test/f.ics")
    monkeypatch.setattr(server, "_timeout", lambda: 0.2)  # shrink the budget for a fast test

    async def slow_fetch(url: str, timeout: float | None = None) -> bytes:
        await asyncio.sleep(30)
        return b""

    monkeypatch.setattr(server, "_fetch", slow_fetch)
    result = asyncio.run(server.health())
    assert result["ok"] is False and "exceeded" in result["detail"]


def test_streaming_fetch_and_health_against_a_local_server(monkeypatch) -> None:
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/calendar")
            self.end_headers()
            self.wfile.write(SAMPLE)

        def log_message(self, *args: object) -> None:
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/cal.ics"
    try:
        raw = asyncio.run(server._fetch(url))
        assert raw.startswith(b"BEGIN:VCALENDAR")
        monkeypatch.setattr(server, "ICS_URLS", url)
        health = asyncio.run(server.health())
        assert health["ok"] is True and health["latency_ms"] is not None
    finally:
        httpd.shutdown()
