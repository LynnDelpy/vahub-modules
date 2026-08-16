"""The weather module's shaping helpers, tested without touching the network."""

from __future__ import annotations

from vahub_mod_weather.server import (
    _clamp,
    describe_code,
    summarize_current,
    summarize_forecast,
    summarize_places,
)


def test_weather_codes_map_to_words() -> None:
    assert describe_code(0) == "clear sky"
    assert describe_code(95) == "thunderstorm"
    assert describe_code(123) == "weather code 123"  # unmapped falls back, not silent
    assert describe_code(None) == "unknown"


def test_current_is_flattened() -> None:
    payload = {
        "current": {
            "temperature_2m": 12.3,
            "apparent_temperature": 10.1,
            "relative_humidity_2m": 80,
            "wind_speed_10m": 15,
            "precipitation": 0.2,
            "weather_code": 61,
            "is_day": 1,
        }
    }
    current = summarize_current(payload)
    assert current["temperature_c"] == 12.3
    assert current["conditions"] == "light rain"
    assert current["is_day"] is True


def test_current_of_a_bad_payload_is_empty() -> None:
    assert summarize_current({"current": "nope"}) == {}
    assert summarize_current(None) == {}


def test_forecast_respects_the_day_count() -> None:
    payload = {
        "daily": {
            "time": ["2026-08-16", "2026-08-17", "2026-08-18"],
            "temperature_2m_max": [24, 25, 22],
            "temperature_2m_min": [14, 15, 13],
            "weather_code": [1, 61, 95],
            "precipitation_sum": [0, 3.2, 8.0],
        }
    }
    days = summarize_forecast(payload, 2)
    assert [d["date"] for d in days] == ["2026-08-16", "2026-08-17"]
    assert days[1]["conditions"] == "light rain"


def test_places_are_summarized() -> None:
    payload = {"results": [{"name": "Zurich", "country": "Switzerland", "latitude": 47.4, "longitude": 8.5}]}
    places = summarize_places(payload, 3)
    assert places[0]["name"] == "Zurich" and places[0]["latitude"] == 47.4


def test_clamp() -> None:
    assert _clamp(99, 3, 1, 7) == 7
    assert _clamp("x", 3, 1, 7) == 3
    assert _clamp(-5, 3, 1, 7) == 1
