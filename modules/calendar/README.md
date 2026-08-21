# calendar module

Your upcoming calendar as read-only tools, from published iCalendar (.ics) feeds.
It backs a dashboard card (what is on today and this week) and lets the assistant
read further ahead or search. It only ever fetches feeds over HTTP, so it can
never change anything on your calendar.

## Configuration

| key | required | meaning |
|---|---|---|
| `CALENDAR_ICS_URLS` | yes | One or more feed URLs, separated by whitespace, commas or newlines. |
| `CALENDAR_USERNAME` | no | HTTP basic-auth user, if a feed is behind auth. |
| `CALENDAR_PASSWORD` | no | HTTP basic-auth password (redacted in the audit log). |
| `CALENDAR_TIMEOUT_S` | no | Per-feed request timeout in seconds. Defaults to 15. |
| `TZ_DEFAULT` | no | IANA zone (e.g. `Europe/Zurich`) for the "today" and "this week" boundaries. Defaults to UTC. |

Where to find a feed URL: Nextcloud and Radicale expose a per-calendar `.ics`
export link, Google Calendar has a "Secret address in iCal format" under a
calendar's settings, and most other calendars have an equivalent subscription
link. Set the value from the hub UI (Modules) or as `VAHUB_MOD_CALENDAR_CALENDAR_ICS_URLS`.

## Tools

| tool | class | what it does |
|---|---|---|
| `summary` | read | Counts for the card (today, next 7 days) plus the next few events. |
| `agenda` | read | Upcoming events over the next N days (1 to 90). |
| `search` | read | Upcoming events whose title, location or calendar matches a query. |

Recurring events are expanded within the window, so a weekly standup shows up on
each day it actually falls. A feed that is unreachable or malformed is reported
under `errors` and never hides the feeds that did load.

All tools are read-class, so the policy gate can allow them without ever exposing
a write. Add a rule per tool in `vahub.yaml` to let the assistant use them.
