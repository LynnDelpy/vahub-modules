"""The weather module: current conditions and a short forecast.

Backed by Open-Meteo, which is free and needs no API key, so this module works
the moment it is installed. It offers three tools: turn a place name into
coordinates, report the current weather at a coordinate, and give a few days of
forecast. The assistant already knows a person's saved places and their
coordinates (through the hub's built-in tools), so it can ask for the weather at
"home" without geocoding; geocode() is for anywhere else.

As in every module here, the tool functions are thin wrappers over helpers the
tests call directly, an out-of-range argument is clamped rather than rejected,
and the health probe reports a backend failure instead of raising it.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

WEATHER_URL = os.environ.get("WEATHER_API_URL", "https://api.open-meteo.com/v1").rstrip("/")
GEOCODING_URL = os.environ.get("GEOCODING_API_URL", "https://geocoding-api.open-meteo.com/v1").rstrip("/")
USER_AGENT = "vahub-mod-weather/0.1 (+https://github.com/LynnDelpy/vahub-modules)"

_weather = httpx.AsyncClient(base_url=WEATHER_URL, timeout=12.0, headers={"user-agent": USER_AGENT})
_geo = httpx.AsyncClient(base_url=GEOCODING_URL, timeout=12.0, headers={"user-agent": USER_AGENT})

mcp = FastMCP("weather")

# Open-Meteo's WMO weather codes, mapped to words a person would use. Unmapped
# codes fall back to the number so the answer is never silently wrong.
_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "depositing rime fog",
    51: "light drizzle", 53: "drizzle", 55: "dense drizzle",
    56: "freezing drizzle", 57: "dense freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    66: "freezing rain", 67: "heavy freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light showers", 81: "showers", 82: "violent showers",
    85: "light snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
}


def describe_code(code: Any) -> str:
    try:
        return _CODES.get(int(code), f"weather code {int(code)}")
    except (TypeError, ValueError):
        return "unknown"


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(int(value), hi))
    except (TypeError, ValueError):
        return default


def summarize_current(payload: Any) -> dict[str, Any]:
    """Pull the current-conditions block into a flat, spoken-friendly shape."""
    current = payload.get("current") if isinstance(payload, dict) else None
    if not isinstance(current, dict):
        return {}
    return {
        "temperature_c": _num(current.get("temperature_2m")),
        "feels_like_c": _num(current.get("apparent_temperature")),
        "humidity_pct": _num(current.get("relative_humidity_2m")),
        "wind_kmh": _num(current.get("wind_speed_10m")),
        "precipitation_mm": _num(current.get("precipitation")),
        "conditions": describe_code(current.get("weather_code")),
        "is_day": bool(current.get("is_day", 1)),
    }


def summarize_forecast(payload: Any, days: int) -> list[dict[str, Any]]:
    daily = payload.get("daily") if isinstance(payload, dict) else None
    if not isinstance(daily, dict):
        return []
    dates = daily.get("time") or []
    highs = daily.get("temperature_2m_max") or []
    lows = daily.get("temperature_2m_min") or []
    codes = daily.get("weather_code") or []
    rain = daily.get("precipitation_sum") or []
    out: list[dict[str, Any]] = []
    for i in range(min(days, len(dates))):
        out.append(
            {
                "date": dates[i],
                "high_c": _num(highs[i]) if i < len(highs) else None,
                "low_c": _num(lows[i]) if i < len(lows) else None,
                "conditions": describe_code(codes[i]) if i < len(codes) else "unknown",
                "precipitation_mm": _num(rain[i]) if i < len(rain) else None,
            }
        )
    return out


def summarize_places(payload: Any, limit: int) -> list[dict[str, Any]]:
    results = payload.get("results") if isinstance(payload, dict) else None
    out: list[dict[str, Any]] = []
    for place in (results if isinstance(results, list) else [])[:limit]:
        if not isinstance(place, dict):
            continue
        out.append(
            {
                "name": place.get("name"),
                "country": place.get("country"),
                "admin": place.get("admin1"),
                "latitude": _num(place.get("latitude")),
                "longitude": _num(place.get("longitude")),
            }
        )
    return out


@mcp.tool()
async def geocode(place: str, limit: int = 3) -> dict[str, Any]:
    """Resolve a place name to coordinates.

    place: a town or city name, e.g. "Zurich" or "Porto, Portugal".
    limit: how many candidates to return (1 to 5).
    """
    capped = _clamp(limit, 3, 1, 5)
    response = await _geo.get("/search", params={"name": place, "count": capped, "language": "en"})
    response.raise_for_status()
    return {"query": place, "places": summarize_places(response.json(), capped)}


@mcp.tool()
async def current_weather(latitude: float, longitude: float) -> dict[str, Any]:
    """Current weather at a coordinate.

    Use a saved place's latitude and longitude, or the result of geocode().
    """
    response = await _weather.get(
        "/forecast",
        params={
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
            "precipitation,weather_code,wind_speed_10m,is_day",
            "wind_speed_unit": "kmh",
            "timezone": "auto",
        },
    )
    response.raise_for_status()
    return {"latitude": latitude, "longitude": longitude, "current": summarize_current(response.json())}


@mcp.tool()
async def forecast(latitude: float, longitude: float, days: int = 3) -> dict[str, Any]:
    """A daily forecast (high, low, conditions, precipitation) at a coordinate.

    days: how many days ahead, 1 to 7.
    """
    capped = _clamp(days, 3, 1, 7)
    response = await _weather.get(
        "/forecast",
        params={
            "latitude": latitude,
            "longitude": longitude,
            "daily": "temperature_2m_max,temperature_2m_min,weather_code,precipitation_sum",
            "forecast_days": capped,
            "timezone": "auto",
        },
    )
    response.raise_for_status()
    return {
        "latitude": latitude,
        "longitude": longitude,
        "days": summarize_forecast(response.json(), capped),
    }


@mcp.tool(name="__health")
async def health() -> dict[str, Any]:
    """Reserved health probe: does the weather API answer?"""
    started = time.monotonic()
    try:
        response = await _weather.get(
            "/forecast", params={"latitude": 0, "longitude": 0, "current": "temperature_2m"}
        )
        ok = response.status_code == 200
        return {
            "ok": ok,
            "backend": "open-meteo.com",
            "latency_ms": round((time.monotonic() - started) * 1000, 1),
            "detail": None if ok else f"status {response.status_code}",
        }
    except Exception as e:
        return {"ok": False, "backend": "open-meteo.com", "latency_ms": None, "detail": str(e)}


def run() -> None:
    mcp.run(transport="stdio")
