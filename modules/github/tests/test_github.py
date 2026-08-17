"""Unit tests for the GitHub module's shaping helpers.

The tools are thin wrappers over these, and over the network, so the parsing and
the "not configured" behaviour are what is worth testing without a token.
"""

from __future__ import annotations

import asyncio

from vahub_mod_github import server


def test_summarize_notifications_flattens_the_useful_fields() -> None:
    payload = [
        {
            "reason": "review_requested",
            "updated_at": "2026-08-16T10:00:00Z",
            "subject": {"title": "Fix the gate", "type": "PullRequest"},
            "repository": {"full_name": "lynn/vahub"},
        },
        "not a dict",  # a malformed entry must be skipped, not crash
    ]
    out = server.summarize_notifications(payload, 10)
    assert out == [
        {
            "repo": "lynn/vahub",
            "title": "Fix the gate",
            "type": "PullRequest",
            "reason": "review_requested",
            "updated_at": "2026-08-16T10:00:00Z",
        }
    ]


def test_summarize_notifications_respects_the_limit() -> None:
    payload = [{"subject": {"title": str(i)}} for i in range(10)]
    assert len(server.summarize_notifications(payload, 3)) == 3


def test_summarize_issues_handles_both_list_and_search_shapes() -> None:
    search = {
        "total_count": 1,
        "items": [
            {
                "title": "Broken",
                "number": 7,
                "html_url": "https://github.com/lynn/vahub/issues/7",
                "repository_url": "https://api.github.com/repos/lynn/vahub",
                "updated_at": "2026-08-16T10:00:00Z",
            }
        ],
    }
    plain = search["items"]
    assert server.summarize_issues(search, 10) == server.summarize_issues(plain, 10)
    one = server.summarize_issues(search, 10)[0]
    assert one["repository"] == "lynn/vahub" and one["is_pull_request"] is False


def test_a_pull_request_is_flagged() -> None:
    items = [{"title": "PR", "pull_request": {"url": "..."}}]
    assert server.summarize_issues(items, 10)[0]["is_pull_request"] is True


def test_repo_from_url_is_tolerant() -> None:
    assert server._repo_from_url("https://api.github.com/repos/lynn/vahub") == "lynn/vahub"
    assert server._repo_from_url("nonsense") is None
    assert server._repo_from_url(None) is None


def test_clamp_keeps_the_limit_in_range() -> None:
    assert server._clamp(999, 20, 1, 50) == 50
    assert server._clamp(0, 20, 1, 50) == 1
    assert server._clamp("x", 20, 1, 50) == 20


def test_tools_report_missing_configuration_rather_than_calling_out(monkeypatch) -> None:
    # With no token, a tool must return a clear, safe message instead of a 401.
    monkeypatch.setattr(server, "TOKEN", "")
    result = asyncio.run(server.summary())
    assert result["configured"] is False and "GITHUB_TOKEN" in result["error"]


def test_health_without_a_token_is_a_clean_not_ok(monkeypatch) -> None:
    monkeypatch.setattr(server, "TOKEN", "")
    health = asyncio.run(server.health())
    assert health["ok"] is False and "GITHUB_TOKEN" in health["detail"]
