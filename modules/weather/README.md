# weather

Current weather and a short forecast, from Open-Meteo. The API is free and needs
no key, so the module works as soon as it is installed.

## Tools

- `geocode(place, limit)`: resolve a place name to coordinates and a country.
- `current_weather(latitude, longitude)`: current temperature, wind,
  precipitation and conditions.
- `forecast(latitude, longitude, days)`: a daily forecast (high, low,
  conditions, precipitation) for the next few days.

The assistant already knows your saved places and their coordinates, so it can
report the weather at "home" without geocoding. `geocode` is for anywhere else.

## Configuration

None required. `WEATHER_API_URL` and `GEOCODING_API_URL` can point at a
self-hosted Open-Meteo instance.

## Policy

```yaml
weather.geocode:
  class: read
  constraints:
    place: { max_len: 120 }
    limit: { range: [1, 5] }
weather.current_weather:
  class: read
  constraints:
    latitude: { range: [-90, 90] }
    longitude: { range: [-180, 180] }
weather.forecast:
  class: read
  constraints:
    latitude: { range: [-90, 90] }
    longitude: { range: [-180, 180] }
    days: { range: [1, 7] }
```
