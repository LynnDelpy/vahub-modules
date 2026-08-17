# github module

Your GitHub inbox as read-only tools: unread notifications, pull requests waiting
for your review, and issues assigned to you. It backs a dashboard card and lets
the assistant look closer. It never writes.

## Configuration

| key | required | meaning |
|---|---|---|
| `GITHUB_TOKEN` | yes | A personal access token with read scopes (notifications, repo/issue read). |
| `GITHUB_API_URL` | no | The API base, for GitHub Enterprise. Defaults to the public API. |
| `GITHUB_TIMEOUT_S` | no | Request timeout in seconds. Defaults to 12. |

Create a token at github.com/settings/tokens. A fine-grained token with read-only
access is enough. Set it from the hub UI (Modules) or as `VAHUB_MOD_GITHUB_GITHUB_TOKEN`.

## Tools

| tool | class | what it does |
|---|---|---|
| `summary` | read | Counts for the card: unread notifications, review requests, assigned issues, plus the most recent few. |
| `notifications` | read | Your unread notifications (repository, title, reason). |
| `assigned_issues` | read | Open issues assigned to you, across repositories. |
| `review_requests` | read | Open pull requests waiting for your review. |
| `search_issues` | read | Search issues and pull requests with a GitHub search query. |

All tools are read-class, so the policy gate can allow them without ever exposing
a write. Add a rule per tool in `vahub.yaml` to let the assistant use them.
