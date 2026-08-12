from __future__ import annotations

from pathlib import Path

from vahub_mod_notify.server import (
    NTFY_PRIORITY,
    PUSHOVER_PRIORITY,
    _read_secret,
    clip,
    normalize_priority,
)


def test_priority_names_are_the_same_on_both_backends() -> None:
    # The tool documents one set of names; each backend maps them to its own
    # scale. A name present in one map and missing from the other would raise
    # a KeyError at send time on that backend only.
    assert set(NTFY_PRIORITY) == set(PUSHOVER_PRIORITY)


def test_unknown_priority_becomes_default() -> None:
    assert normalize_priority("URGENT") == "urgent"
    assert normalize_priority("catastrophic") == "default"
    assert normalize_priority(None) == "default"
    assert normalize_priority(7) == "default"


def test_clip_bounds_the_field_and_marks_the_cut() -> None:
    assert clip("  hello  ", 40) == "hello"
    clipped = clip("x" * 200, 10)
    assert len(clipped) == 10
    assert clipped.endswith("...")
    assert clip(None, 10) == ""


def test_secret_falls_back_to_a_file(tmp_path: Path, monkeypatch) -> None:
    secret = tmp_path / "token"
    secret.write_text("tok_from_file\n")
    monkeypatch.delenv("TEST_TOKEN", raising=False)
    monkeypatch.setenv("TEST_TOKEN_FILE", str(secret))
    assert _read_secret("TEST_TOKEN", "TEST_TOKEN_FILE") == "tok_from_file"

    monkeypatch.setenv("TEST_TOKEN", "tok_from_env")
    assert _read_secret("TEST_TOKEN", "TEST_TOKEN_FILE") == "tok_from_env"


def test_missing_secret_is_empty_not_an_error(monkeypatch) -> None:
    monkeypatch.delenv("TEST_TOKEN", raising=False)
    monkeypatch.setenv("TEST_TOKEN_FILE", "/nonexistent/path")
    assert _read_secret("TEST_TOKEN", "TEST_TOKEN_FILE") == ""
