# time

The current time, in a timezone of your choosing. No backend, no credentials,
no network. It exists so you can prove the hub, the supervisor and the policy
gate work before you point anything at your house, and it is the worked example
the rest of this repository refers to.

## Install

```
vahub module add time
```

## Tools

| Tool | Class | What it does |
| --- | --- | --- |
| `get_current_time` | read | Current date and time as an ISO-8601 string, for example `2026-08-12T07:05:00+02:00`. |
| `speak_current_time` | read | Current time as a phrase a voice can read: `It is 07:05.` |
| `__health` | reserved | Always healthy. There is no backend to be unreachable. |

Both tools take an optional `tz`, an IANA timezone name such as `Europe/Zurich`.
A name the module cannot resolve falls back to the configured default rather
than failing, because the value usually comes from a language model.

## Config

| Key | Required | Default | Meaning |
| --- | --- | --- | --- |
| `TZ_DEFAULT` | no | `UTC` | Timezone used when the caller does not name one. |

Config reaches the module as environment variables, and only the keys listed in
`module.yaml` are passed through. Set it wherever the hub process gets its
environment (the systemd unit, the compose file, your shell during development):

```
TZ_DEFAULT=Europe/Zurich
```

## Policy

Nothing here can change the world, so a plain read rule is enough. Paste into
`vahub.yaml`:

```yaml
policy:
  default: deny
  rules:
    "time.get_current_time":
      class: read
      constraints:
        tz:
          matches: "^[A-Za-z]+/[A-Za-z_+-]+$"
    "time.speak_current_time":
      class: read
      constraints:
        tz:
          matches: "^[A-Za-z]+/[A-Za-z_+-]+$"
```

The `tz` constraint is not optional decoration. The gate rejects any argument it
was not told about, so a rule with no `constraints` block permits only calls
with no arguments at all.

## Development

```
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
```

To run it against a hub without publishing anything, install from the working
copy:

```
vahub module add --source ./modules/time
```
