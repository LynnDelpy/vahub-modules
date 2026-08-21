# rss module

Your RSS and Atom feeds as read-only tools: the latest items across everything
you follow, one feed at a time, or a search. It backs a dashboard card and lets
the assistant read further. It only ever fetches feeds, so it can never change
anything.

## Configuration

| key | required | meaning |
|---|---|---|
| `RSS_FEEDS` | yes | One or more feed URLs, separated by whitespace, commas or newlines. RSS and Atom both work. |
| `RSS_TIMEOUT_S` | no | Per-feed request timeout in seconds. Defaults to 12. |
| `RSS_MAX_PER_FEED` | no | How many items to read from each feed before merging. Defaults to 25 (max 100). |

Set the value from the hub UI (Modules) or as `VAHUB_MOD_RSS_RSS_FEEDS`.

## Tools

| tool | class | what it does |
|---|---|---|
| `summary` | read | The most recent items across all feeds, for the card. |
| `latest` | read | The most recent items across all your feeds, newest first. |
| `feed` | read | Items from one feed, matched by its title or host. |
| `search` | read | Items whose title, summary or feed matches a query. |

Items are merged newest first across feeds; one whose date cannot be read sorts
last rather than being dropped. Summaries are reduced to plain text. A feed that
is unreachable or malformed is reported under `errors` and never hides the feeds
that did load.

All tools are read-class, so the policy gate can allow them without ever exposing
a write. Add a rule per tool in `vahub.yaml` to let the assistant use them.
