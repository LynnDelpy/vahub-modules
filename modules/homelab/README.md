# homelab module

Is everything up? This module probes a list of your services and reports which
answer. It backs a dashboard card (up/down at a glance) and lets the assistant
re-check on demand. It only ever does a plain HTTP GET or opens a TCP connection,
so it can observe a service but never act on one.

## Configuration

| key | required | meaning |
|---|---|---|
| `HOMELAB_TARGETS` | yes | A JSON array of targets (see below). |
| `HOMELAB_TIMEOUT_S` | no | Per-probe timeout in seconds. Defaults to 5. |
| `HOMELAB_VERIFY_SSL` | no | Verify TLS certificates on HTTPS checks. Defaults to true. |

Each target is an object with a `name` and either:

- an HTTP check: `"url"`, and optionally `"expect_status"` (if omitted, any 2xx or
  3xx counts as up); or
- a TCP check: `"host"` and `"port"` (up when a connection opens).

```json
[
  {"name": "Nextcloud", "url": "https://cloud.home", "expect_status": 200},
  {"name": "Router",    "url": "http://10.0.0.1"},
  {"name": "SSH",       "host": "10.0.0.2", "port": 22}
]
```

Set the value from the hub UI (Modules) or as `VAHUB_MOD_HOMELAB_HOMELAB_TARGETS`.
Redirects are not followed and no request body is sent, so a check cannot trigger
an action behind a URL.

## Tools

| tool | class | what it does |
|---|---|---|
| `summary` | read | Up/down counts and per-target status, for the card. |
| `check` | read | Probe every target now, or just the one named. |

The health probe reports on the module (is the target list present and valid),
not on the services: a service being down is what the tools report, so it never
makes the module itself look unhealthy.

All tools are read-class, so the policy gate can allow them without ever exposing
a write. Add a rule per tool in `vahub.yaml` to let the assistant use them.
