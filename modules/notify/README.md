# notify

Sends a push notification to your phone. Two backends: ntfy (no account needed)
and Pushover (needs an application token and a user key).

## Install

```
vahub module add notify
```

## Tools

| Tool | Class | What it does |
| --- | --- | --- |
| `send_push` | write | Sends a notification with `title`, `message`, `priority` and optional `tags`. |
| `__health` | reserved | Checks that the chosen backend is configured and answering. It never sends a notification. |

`priority` is one of `min`, `low`, `default`, `high`, `urgent`. Each backend maps
those names onto its own scale. Pushover's emergency level, which retries until
someone acknowledges it, is not reachable from here. `tags` is passed to ntfy as
its emoji short codes (`warning,house`) and ignored by Pushover.

The tool is `write`, not `read`. A notification leaves the machine and arrives
on a device you cannot un-notify, so it belongs behind a rule.

## Config

| Key | Backend | Meaning |
| --- | --- | --- |
| `NOTIFY_BACKEND` | both | `ntfy` (default) or `pushover`. |
| `NTFY_URL` | ntfy | Base URL, default `https://ntfy.sh`. A self-hosted server works. |
| `NTFY_TOPIC` | ntfy | Topic to publish to. Required for this backend. |
| `NTFY_TOKEN` / `NTFY_TOKEN_FILE` | ntfy | Access token, only needed for a protected topic. |
| `PUSHOVER_TOKEN` / `PUSHOVER_TOKEN_FILE` | pushover | Application token from pushover.net. |
| `PUSHOVER_USER` / `PUSHOVER_USER_FILE` | pushover | User or group key. |

Every secret can come from a file instead of the environment. Set the `_FILE`
variant to a path and leave the plain variable unset. That is how a systemd
credential or a Docker secret is handed over without the value appearing in a
unit file or in `ps`:

```
NOTIFY_BACKEND=pushover
PUSHOVER_TOKEN_FILE=/run/credentials/vahub.service/pushover_token
PUSHOVER_USER_FILE=/run/credentials/vahub.service/pushover_user
```

On the public ntfy.sh a topic name is the only access control there is: anyone
who knows it can read your notifications and publish their own. Choose something
unguessable, or self-host. The manifest lists `NTFY_TOPIC` under `audit.redact`
for the same reason it lists the tokens.

## Policy

Paste into `vahub.yaml`. Bounding the text matters here: without `max_len` the
model can send an essay, and without a `priority` constraint it can decide that
everything is urgent.

```yaml
policy:
  default: deny
  rules:
    "notify.send_push":
      class: write
      constraints:
        title:
          max_len: 80
        message:
          max_len: 400
        priority:
          in: ["min", "low", "default", "high"]
        tags:
          matches: "^[a-z0-9_,+-]{0,60}$"
```

`urgent` is left out of that list deliberately. Add it once you trust the setup
enough to be woken by it.

A routine that reports on something each morning pairs well with this:

```yaml
schedules:
  - id: morning-note
    cron: "30 6 * * *"
    steps:
      - module: notify
        tool: send_push
        args:
          title: "Good morning"
          message: "The heating is on and the front door is locked."
          priority: low
```

Scheduled steps go through the same gate as anything the model asks for, under
the `scheduler` principal.

## Development

```
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
```

To try it by hand, set `NTFY_TOPIC` to a fresh random name, subscribe to it in
the ntfy app, and call the tool through the hub's dev tools endpoint.
