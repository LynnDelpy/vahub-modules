# transit

Swiss public transport, through the free transport.opendata.ch API. No key, no
account, read-only.

## Install

```
vahub module add transit
```

## Tools

| Tool | Class | What it does |
| --- | --- | --- |
| `find_connections` | read | Journeys between two places, with legs, transfers and duration. Accepts `arrive_by` or `depart_at` as `HH:MM` and an optional `date`. |
| `next_departures` | read | Departure board for one station. |
| `__health` | reserved | One small request to the API, reporting reachability and latency. |

Times are returned as `07:52` and durations as `23 min` or `1h05`, because the
answer is usually spoken. Place names take the form the API understands: station
names like `Basel SBB`, or a street with its town, `Haldenweg 15, Basel`.

## Config

| Key | Required | Default | Meaning |
| --- | --- | --- | --- |
| `TRANSIT_API_URL` | no | `https://transport.opendata.ch/v1` | Point at a mirror or a local stub for testing. |
| `TZ_DEFAULT` | no | `Europe/Zurich` | Timezone used to work out what "today" means. |

The upstream API is a free community service with no formal rate limit. The
health probe therefore runs every two minutes rather than every thirty seconds,
and both tools cap how many results they request.

## Policy

Paste into `vahub.yaml`. Both tools are read-only, but they do send whatever
strings the model produces to a third party, so `max_len` is worth setting.

```yaml
policy:
  default: deny
  rules:
    "transit.find_connections":
      class: read
      constraints:
        origin:
          max_len: 80
        destination:
          max_len: 80
        arrive_by:
          matches: "^[0-2][0-9]:[0-5][0-9]$"
        depart_at:
          matches: "^[0-2][0-9]:[0-5][0-9]$"
        date:
          matches: "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
        limit:
          range: [1, 6]
    "transit.next_departures":
      class: read
      constraints:
        station:
          max_len: 80
        limit:
          range: [1, 12]
```

A scheduled routine that reads out the next departures each morning is a natural
use for this module:

```yaml
schedules:
  - id: morning-departures
    cron: "0 7 * * 1-5"
    steps:
      - module: transit
        tool: next_departures
        args: { station: "Basel SBB", limit: 3 }
```

## Development

```
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
```

The tests cover the formatting and the parsing of unexpected payloads. They do
not call the network.
