from __future__ import annotations

from vahub_mod_transit.server import clock, duration, legs, summarize_board, summarize_connections


def test_clock_drops_date_and_offset() -> None:
    assert clock("2026-07-27T07:52:00+02:00") == "07:52"
    assert clock(None) is None


def test_clock_passes_through_what_it_cannot_parse() -> None:
    # Losing a departure time is worse than showing it in an odd format.
    assert clock("soon") == "soon"


def test_duration_reads_like_speech() -> None:
    assert duration("00d00:23:00") == "23 min"
    assert duration("00d01:05:00") == "1h05"
    assert duration("01d00:00:00") == "24h00"
    assert duration(None) is None
    assert duration("weird") == "weird"


def test_legs_covers_journeys_and_walks() -> None:
    sections = [
        {
            "journey": {"category": "S", "number": "3"},
            "departure": {"station": {"name": "Basel SBB"}, "departure": "2026-07-27T07:52:00+02:00"},
            "arrival": {"station": {"name": "Liestal"}, "arrival": "2026-07-27T08:05:00+02:00"},
        },
        {"walk": {"duration": 300}, "departure": {"station": {"name": "Liestal"}}, "arrival": None},
    ]
    result = legs(sections)
    assert result[0] == {
        "line": "S 3",
        "from": "Basel SBB",
        "to": "Liestal",
        "departure": "07:52",
        "arrival": "08:05",
    }
    assert result[1] == {"walk": True, "from": "Liestal", "to": None}


def test_summaries_survive_a_backend_that_changes_shape() -> None:
    assert summarize_connections({"connections": "nope"}, 4) == []
    assert summarize_connections([], 4) == []
    assert summarize_board({"stationboard": [None, 3]}, 6) == []
    assert legs("not a list") == []


def test_limit_is_respected() -> None:
    payload = {"connections": [{"from": {}, "to": {}} for _ in range(10)]}
    assert len(summarize_connections(payload, 2)) == 2
