# gitlab module

Your GitLab attention list as read-only tools: pending to-dos, merge requests
assigned to you, and issues assigned to you. It backs a dashboard card and lets
the assistant look closer. It never writes.

## Configuration

| key | required | meaning |
|---|---|---|
| `GITLAB_TOKEN` | yes | A personal access token with the `read_api` scope. |
| `GITLAB_API_URL` | no | The API base, for a self-managed instance. Defaults to `https://gitlab.com/api/v4`. |
| `GITLAB_TIMEOUT_S` | no | Request timeout in seconds. Defaults to 12. |

Create a token under Preferences, Access Tokens. `read_api` is enough. Set it
from the hub UI (Modules) or as `VAHUB_MOD_GITLAB_GITLAB_TOKEN`.

## Tools

| tool | class | what it does |
|---|---|---|
| `summary` | read | Counts for the card: pending to-dos, assigned merge requests and issues, plus the most recent to-dos. |
| `todos` | read | Your pending to-dos. |
| `assigned_merge_requests` | read | Open merge requests assigned to you. |
| `assigned_issues` | read | Open issues assigned to you. |

All tools are read-class, so the policy gate can allow them without ever exposing
a write. Add a rule per tool in `vahub.yaml` to let the assistant use them.
