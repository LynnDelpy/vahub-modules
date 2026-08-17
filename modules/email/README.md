# email module

A read-only view of a mailbox over IMAP: how much unread mail there is, from
whom, and a search. It backs a dashboard card and lets the assistant look at
recent or matching messages. It never sends, deletes, or marks a message read,
and it never fetches a message body, only the From, Subject and Date headers.

## Configuration

| key | required | meaning |
|---|---|---|
| `EMAIL_HOST` | yes | IMAP server hostname, e.g. `imap.fastmail.com`. |
| `EMAIL_USERNAME` | yes | The account to log in as. |
| `EMAIL_PASSWORD` | yes | The password. Use an app password where the provider offers one. |
| `EMAIL_PORT` | no | IMAP port. Defaults to 993 (SSL) or 143 (plain). |
| `EMAIL_SSL` | no | `true` (default) uses IMAP over SSL; `false` uses a plain connection. |
| `EMAIL_MAILBOX` | no | Which mailbox to read. Defaults to `INBOX`. |
| `EMAIL_TIMEOUT_S` | no | Connection timeout in seconds. Defaults to 15. |

Set these from the hub UI (Modules) or as `VAHUB_MOD_EMAIL_EMAIL_PASSWORD`, and so
on. Prefer a provider app password over your real account password.

## Tools

| tool | class | what it does |
|---|---|---|
| `summary` | read | Unread count, total count, and the most recent few messages. |
| `list_unread` | read | Recent unread messages (from, subject, date). Does not mark them read. |
| `search` | read | Search the mailbox for messages whose text matches a query. |

All tools are read-class, so the policy gate can allow them without ever exposing
a way to send or delete. Add a rule per tool in `vahub.yaml` to let the assistant
use them.
