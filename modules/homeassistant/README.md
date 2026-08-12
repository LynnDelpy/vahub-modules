# homeassistant

Lights, locks and sensor readings through the Home Assistant REST API, using a
long-lived access token.

## Install

```
vahub module add homeassistant
```

## Tools

| Tool | Class | What it does |
| --- | --- | --- |
| `list_entities` | read | Entity ids and states, filtered by domain (`light`, `lock`, `sensor`, ...), capped at 200 entries. |
| `get_state` | read | State and attributes of one entity. |
| `light_turn_on` | write | Turn a light on, optionally at `brightness_pct` 1 to 100. |
| `light_turn_off` | write | Turn a light off. |
| `lock_lock` | write | Lock a lock. |
| `lock_unlock` | destructive | Unlock a lock. |
| `__health` | reserved | Reports whether Home Assistant answers and whether the token is accepted. |

There is no generic `call_service` tool, and that is on purpose. A pass-through
to `POST /api/services/{domain}/{service}` can do anything the instance can do,
so the gate would have nothing to constrain except the literal string
`call_service`. Rules such as "may dim the living room light, may never touch a
lock" only exist because each action is its own named tool with its own class.
If you need a service that is not here, add a named tool for it.

## Config

| Key | Required | Default | Meaning |
| --- | --- | --- | --- |
| `HA_URL` | yes | falls back to `http://localhost:8123` | Base URL of your Home Assistant. |
| `HA_TOKEN` | one of the two | none | Long-lived access token (Profile, Security, Long-lived access tokens). |
| `HA_TOKEN_FILE` | one of the two | none | Path to a file holding the token, for systemd credentials or Docker secrets. |
| `HA_VERIFY_SSL` | no | `true` | Set `false` only for a self-signed certificate on your own network. |
| `HA_TIMEOUT_S` | no | `10` | HTTP timeout in seconds. |

`HA_TOKEN` is listed in `audit.redact`, so it is scrubbed from audit records.
The module never logs it. Only the keys named in `module.yaml` are passed to the
process, so no other module can read this token.

Create a token scoped to a dedicated Home Assistant user rather than your own
account. Home Assistant tokens carry the permissions of their user, and the
narrow tool set here is a property of this module, not of the token.

## Policy

Paste into `vahub.yaml` and edit the entity lists to match your home. The gate
rejects any argument that has no constraint entry, so every argument the model
may pass needs one.

```yaml
policy:
  default: deny
  confirm_ttl_s: 60
  principals:
    agent:
      confirm: [destructive]
    scheduler:
      # Unattended runs read and switch lights. They never touch a lock.
      deny: ["homeassistant.lock_*"]
  rules:
    "homeassistant.list_entities":
      class: read
      constraints:
        domain:
          in: ["light", "lock", "sensor", "switch", "binary_sensor", "climate"]
        limit:
          range: [1, 200]
    "homeassistant.get_state":
      class: read
      constraints:
        entity_id:
          matches: "^(light|lock|sensor|switch|binary_sensor|climate)\\.[a-z0-9_]+$"
    "homeassistant.light_turn_on":
      class: write
      constraints:
        entity_id:
          in: ["light.living_room", "light.kitchen", "light.bedroom"]
        brightness_pct:
          range: [1, 100]
    "homeassistant.light_turn_off":
      class: write
      constraints:
        entity_id:
          in: ["light.living_room", "light.kitchen", "light.bedroom"]
    "homeassistant.lock_lock":
      class: write
      constraints:
        entity_id:
          in: ["lock.front_door"]
    "homeassistant.lock_unlock":
      class: destructive
      constraints:
        entity_id:
          in: ["lock.front_door"]
```

Two habits worth keeping. List entity ids explicitly for anything that acts on
the physical world, since a regex that matches `light.*` also matches the light
you forgot about. And leave `lock_unlock` out of the rules entirely until you
have decided you want it: with `default: deny`, a tool that is not mentioned
cannot be called.

## Development

```
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
```

The tests cover the parsing and clamping, not the network. Point `HA_URL` at a
throwaway instance for anything more.
