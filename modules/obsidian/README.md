# obsidian module

A read-only window onto an Obsidian vault of Markdown notes. It backs a dashboard
card (today's daily note and what you touched recently) and lets the assistant
search the vault or read a note. It never writes, moves or deletes anything.

## Configuration

| key | required | meaning |
|---|---|---|
| `OBSIDIAN_VAULT_PATH` | yes | The vault directory the module may read. |
| `OBSIDIAN_SUBDIR` | no | Narrow reads to a subtree of the vault (e.g. `Projects`). Everything outside it stays out of reach. |
| `OBSIDIAN_DAILY_DIR` | no | The folder holding daily notes, if they live in one. |
| `OBSIDIAN_DAILY_FORMAT` | no | strftime pattern for a daily note's filename. Defaults to `%Y-%m-%d`. |
| `TZ_DEFAULT` | no | IANA zone for "today" and for note timestamps. Defaults to UTC. |

The module reads only files under the resolved root (vault, narrowed by
`OBSIDIAN_SUBDIR`). Every path a tool is given is resolved and confirmed to be
inside that root before it is opened, so a `..` or an absolute path cannot escape
it. Hidden directories (a leading dot, such as `.obsidian` or `.git`) are
skipped, and only Markdown files are read.

If you run the hub sandboxed (Docker, or a per-module uid), the vault has to be
readable by that account, so mount it read-only into the module's view.

## Tools

| tool | class | what it does |
|---|---|---|
| `summary` | read | Today's daily note plus recently modified notes, for the card. |
| `daily` | read | The daily note for a date (default today). |
| `search` | read | Notes whose filename or content matches a query, with a snippet. |
| `note` | read | Read one note by its vault-relative path. |
| `recent` | read | The notes modified most recently, newest first. |

All tools are read-class, so the policy gate can allow them without ever exposing
a write. Add a rule per tool in `vahub.yaml` to let the assistant use them.
