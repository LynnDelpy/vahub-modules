# vahub-modules

Modules for [vahub](https://github.com/LynnDelpy/vahub), a self-hosted voice
assistant hub. A module is a separate program that speaks MCP over stdin and
stdout. The hub spawns it, hands it only the configuration it declared, gates
every call against your policy, and can kill it. Nothing here is imported by the
hub, and nothing here can grant itself permission.

This repository is two things: a handful of first-party modules, and
`registry.json`, an index that lets `vahub module add <name>` find a module by
name. It is not a gate. A module can live in any git repository, public or
private, and install exactly the same way. Being listed here is a convenience
for other people, not a licence to run.

## Catalogue

| Module | What it does | Config it needs |
| --- | --- | --- |
| [time](modules/time) | Current time and date, as ISO text or as a phrase to read aloud. | none (`TZ_DEFAULT` optional) |
| [homeassistant](modules/homeassistant) | Lights, locks and sensor readings through Home Assistant. Narrow tools, no generic service call. | `HA_URL`, and `HA_TOKEN` or `HA_TOKEN_FILE` |
| [transit](modules/transit) | Swiss public transport: connections and departure boards, via transport.opendata.ch. | none, no API key exists |
| [notify](modules/notify) | Push notifications to a phone via ntfy or Pushover. | ntfy: `NTFY_TOPIC`. Pushover: `PUSHOVER_TOKEN` and `PUSHOVER_USER` |
| [weather](modules/weather) | Current weather and a short forecast, from the free Open-Meteo API. | none, no API key exists |
| [calculator](modules/calculator) | Evaluate arithmetic safely, with common math functions. Never uses eval(). | none |
| [github](modules/github) | Your GitHub notifications, review requests and assigned issues. Read-only, backs a dashboard card. | `GITHUB_TOKEN` |
| [gitlab](modules/gitlab) | Your GitLab to-dos, assigned merge requests and issues. Read-only, backs a dashboard card. | `GITLAB_TOKEN` |
| [email](modules/email) | Read-only view of a mailbox over IMAP: unread count and recent messages. | `EMAIL_HOST`, `EMAIL_USERNAME`, `EMAIL_PASSWORD` |
| [calendar](modules/calendar) | Upcoming events from published ICS feeds. Read-only, backs a dashboard card. | `CALENDAR_ICS_URLS` |
| [rss](modules/rss) | Latest items from your RSS and Atom feeds. Read-only, backs a dashboard card. | `RSS_FEEDS` |
| [obsidian](modules/obsidian) | Read-only view of an Obsidian vault: daily note, recent notes and search. | `OBSIDIAN_VAULT_PATH` |
| [homelab](modules/homelab) | Up/down status of your self-hosted services, via HTTP and TCP checks. | `HOMELAB_TARGETS` |

Each module's README lists its tools, its config keys and a policy block you can
paste into `vahub.yaml`.

## Installing a module

From the index, by name:

```
vahub module search light
vahub module add homeassistant
vahub module list
```

From anywhere else, by pinned source:

```
vahub module add --source git+https://example.com/my-modules.git@v1.0.0#subdir=modules/weather
vahub module add --source pypi:vahub-mod-weather==1.0.0
vahub module add --source ./modules/time
```

A git source must be pinned to a tag or a commit sha. Installing from a branch
is refused, because "whatever main happens to be today" is not something to
point at your front door.

Installing creates a virtualenv for the module, installs it there, and writes
its manifest into `/etc/vahub/modules.d/`. Nothing is running yet: the hub reads
your policy, and with `policy.default: deny` a tool nobody wrote a rule for
cannot be called. Start with the `time` module, confirm the hub can spawn it and
call it, then move on to something that touches the world.

Configuration reaches a module as environment variables, and only the keys its
manifest declares are passed through. That is why one module cannot read
another's token, and why a module you install cannot see your language model API
key.

## Writing your own

Copy [template/](template), which is a working module with one tool, a health
probe, a manifest and a test. Its README explains the three steps to make it
yours. The [time](modules/time) module is the same idea with the comments an
implementer actually needs.

The rules a module has to follow are short:

* Implement `__health`, returning `{ok, backend, latency_ms, detail}`. The hub
  calls it on a timer to tell "the process is up" from "the backend answers".
* Declare every config key you read, and every secret under `audit.redact`.
* Declare each tool with a class: `read`, `write`, or `destructive` for anything
  a person would want to be asked about first.
* Prefer several narrow tools over one general one. The gate authorizes by tool
  name and argument values, so a pass-through tool is a hole in it.
* Report failures, do not raise them, and never assume the backend returned the
  shape its documentation promises.

## Getting a module listed

Open a pull request adding your directory and a `registry.json` entry. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the steps and for what the review looks
at. You do not have to do this: publishing a module in your own repository and
telling people the pinned source works just as well.

## Trust

Installing a module runs somebody else's code on your machine, with whatever
configuration you give it. The registry makes that convenient; it does not make
it safe. Review a module before you install it, especially one that asks for a
token. The hub's own defences (a minimal environment per module, a separate
process, an optional unprivileged account per module, and a policy gate in front
of every call) are what limits the damage a bad module can do, and they are worth
reading about in the hub's documentation before you install anything that can
open a door.

## Licence

MIT. See [LICENSE](LICENSE).

## The vahub project

Three repositories, one project:

- [vahub](https://github.com/LynnDelpy/vahub). The hub itself.
- [vahub-modules](https://github.com/LynnDelpy/vahub-modules) (this one). The catalog and first-party modules.
- [vahub-docs](https://github.com/LynnDelpy/vahub-docs). The full documentation.
