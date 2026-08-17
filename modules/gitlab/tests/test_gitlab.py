"""Unit tests for the GitLab module's shaping helpers."""

from __future__ import annotations

import asyncio

from vahub_mod_gitlab import server


def test_summarize_todos_flattens_the_useful_fields() -> None:
    payload = [
        {
            "target_type": "MergeRequest",
            "action_name": "review_requested",
            "target": {"title": "Fix the gate"},
            "project": {"name_with_namespace": "Lynn / vahub"},
            "target_url": "https://gitlab.com/lynn/vahub/-/merge_requests/3",
        },
        "not a dict",  # skipped, not a crash
    ]
    out = server.summarize_todos(payload, 10)
    assert out == [
        {
            "type": "MergeRequest",
            "title": "Fix the gate",
            "action": "review_requested",
            "project": "Lynn / vahub",
            "url": "https://gitlab.com/lynn/vahub/-/merge_requests/3",
        }
    ]


def test_summarize_todos_falls_back_to_the_body() -> None:
    payload = [{"body": "Something to do", "target": {}}]
    assert server.summarize_todos(payload, 10)[0]["title"] == "Something to do"


def test_summarize_items_shapes_mrs_and_issues() -> None:
    payload = [
        {
            "title": "Add tests",
            "reference": "!3",
            "references": {"full": "lynn/vahub!3"},
            "web_url": "https://gitlab.com/lynn/vahub/-/merge_requests/3",
            "updated_at": "2026-08-16T10:00:00Z",
        }
    ]
    one = server.summarize_items(payload, 10)[0]
    assert one["title"] == "Add tests" and one["project"] == "lynn/vahub!3"
    assert one["url"].endswith("/merge_requests/3")


def test_total_prefers_the_header(monkeypatch) -> None:
    import httpx

    response = httpx.Response(200, headers={"x-total": "42"})
    assert server._total(response, [{"a": 1}]) == 42
    bare = httpx.Response(200)
    assert server._total(bare, [{"a": 1}, {"b": 2}]) == 2


def test_clamp_keeps_the_limit_in_range() -> None:
    assert server._clamp(999, 20, 1, 50) == 50
    assert server._clamp(0, 20, 1, 50) == 1
    assert server._clamp("x", 20, 1, 50) == 20


def test_tools_report_missing_configuration(monkeypatch) -> None:
    monkeypatch.setattr(server, "TOKEN", "")
    result = asyncio.run(server.summary())
    assert result["configured"] is False and "GITLAB_TOKEN" in result["error"]


def test_health_without_a_token_is_a_clean_not_ok(monkeypatch) -> None:
    monkeypatch.setattr(server, "TOKEN", "")
    health = asyncio.run(server.health())
    assert health["ok"] is False and "GITLAB_TOKEN" in health["detail"]
