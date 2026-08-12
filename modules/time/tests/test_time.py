from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from vahub_mod_time.server import health, resolve_zone, spoken_time


def test_known_zone_is_used() -> None:
    assert resolve_zone("Europe/Zurich") == ZoneInfo("Europe/Zurich")


def test_unknown_zone_falls_back_instead_of_raising() -> None:
    # A model can invent "Europe/Basel". Answering in the default zone beats
    # turning a plausible typo into a spoken error.
    assert resolve_zone("Europe/Nowhere") == ZoneInfo("UTC")
    assert resolve_zone(None) == ZoneInfo("UTC")


def test_spoken_time_has_no_seconds_or_offset() -> None:
    moment = datetime(2026, 8, 12, 7, 5, tzinfo=ZoneInfo("Europe/Zurich"))
    assert spoken_time(moment) == "It is 07:05."


def test_health_shape_matches_the_contract() -> None:
    result = health()
    assert set(result) == {"ok", "backend", "latency_ms", "detail"}
    assert result["ok"] is True
