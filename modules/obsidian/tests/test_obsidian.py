"""Unit tests for the Obsidian module's filesystem helpers.

The tools are thin wrappers over these, so the path-safety guard, the vault
scan, search and the "not configured" behaviour are what is worth testing. Every
test builds a small vault under tmp_path.
"""

from __future__ import annotations

import asyncio
import os
from datetime import date
from zoneinfo import ZoneInfo

from vahub_mod_obsidian import server

UTC = ZoneInfo("UTC")


def _vault(tmp_path):
    (tmp_path / "note1.md").write_text("# Title One\n\ncontent alpha here\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "note2.md").write_text("beta content in a nested note\n")
    (tmp_path / "data.txt").write_text("not a markdown file\n")
    hidden = tmp_path / ".obsidian"
    hidden.mkdir()
    (hidden / "workspace.md").write_text("# internal\nshould be invisible\n")
    return tmp_path


def test_safe_join_rejects_traversal_and_absolutes(tmp_path) -> None:
    root = _vault(tmp_path)
    (tmp_path.parent / "secret.md").write_text("secret\n")
    assert server.safe_join(root, "../secret.md") is None
    assert server.safe_join(root, "/etc/passwd") is None
    assert server.safe_join(root, "note1.md") == root / "note1.md"


def test_safe_join_only_returns_markdown_files(tmp_path) -> None:
    root = _vault(tmp_path)
    assert server.safe_join(root, "data.txt") is None
    assert server.safe_join(root, "missing.md") is None
    assert server.safe_join(root, "sub/note2.md") == root / "sub" / "note2.md"


def test_iter_markdown_skips_hidden_dirs_and_non_markdown(tmp_path) -> None:
    root = _vault(tmp_path)
    found = {p.relative_to(root).as_posix() for p in server.iter_markdown(root)}
    assert found == {"note1.md", "sub/note2.md"}


def test_resolve_root_honours_subdir_and_rejects_escape(tmp_path) -> None:
    root = _vault(tmp_path)
    assert server.resolve_root(str(root), "sub") == root / "sub"
    # A file in the vault root is invisible when the root is narrowed to sub/.
    scoped = server.resolve_root(str(root), "sub")
    assert {p.name for p in server.iter_markdown(scoped)} == {"note2.md"}
    assert server.resolve_root(str(root), "../..") is None
    assert server.resolve_root("", "") is None
    assert server.resolve_root(str(root / "does-not-exist"), "") is None


def test_search_finds_content_and_filename_matches(tmp_path) -> None:
    root = _vault(tmp_path)
    by_content = server.search_notes(root, "alpha", 10, UTC)
    assert len(by_content) == 1
    assert by_content[0]["path"] == "note1.md"
    assert "alpha" in by_content[0]["snippet"]
    by_name = server.search_notes(root, "note2", 10, UTC)
    assert [r["path"] for r in by_name] == ["sub/note2.md"]
    assert server.search_notes(root, "", 10, UTC) == []


def test_recent_notes_orders_by_mtime(tmp_path) -> None:
    root = _vault(tmp_path)
    os.utime(root / "note1.md", (1000, 1000))
    os.utime(root / "sub" / "note2.md", (2000, 2000))
    ordered = [n["path"] for n in server.recent_notes(root, 10, UTC)]
    assert ordered == ["sub/note2.md", "note1.md"]


def test_note_title_prefers_the_first_heading(tmp_path) -> None:
    assert server.note_title(tmp_path / "x.md", "# Real Title\nbody") == "Real Title"
    assert server.note_title(tmp_path / "fallback.md", "no heading here") == "fallback"


def test_excerpt_drops_frontmatter_and_collapses_whitespace() -> None:
    text = "---\ntags: [a, b]\ndate: 2026-01-01\n---\n\nThe   body   begins here.\n"
    assert server.excerpt(text) == "The body begins here."


def test_daily_path_composition_and_containment(tmp_path) -> None:
    root = _vault(tmp_path)
    day = date(2026, 1, 15)
    assert server.daily_path(root, "", "%Y-%m-%d", day) == root / "2026-01-15.md"
    assert server.daily_path(root, "Daily", "%Y-%m-%d", day) == root / "Daily" / "2026-01-15.md"


def test_tools_report_missing_configuration(monkeypatch) -> None:
    monkeypatch.setattr(server, "VAULT_PATH", "")
    result = asyncio.run(server.summary())
    assert result["configured"] is False and "OBSIDIAN_VAULT_PATH" in result["error"]
    health = asyncio.run(server.health())
    assert health["ok"] is False and "OBSIDIAN_VAULT_PATH" in health["detail"]


def test_note_tool_reads_within_the_vault(tmp_path, monkeypatch) -> None:
    root = _vault(tmp_path)
    monkeypatch.setattr(server, "VAULT_PATH", str(root))
    monkeypatch.setattr(server, "SUBDIR", "")
    good = asyncio.run(server.note("note1.md"))
    assert good["title"] == "Title One" and "alpha" in good["content"]
    escape = asyncio.run(server.note("../secret.md"))
    assert "error" in escape


def test_scan_excludes_symlinks_that_escape_the_vault(tmp_path) -> None:
    root = _vault(tmp_path)
    secret = tmp_path.parent / "outside_secret.md"
    secret.write_text("TOP SECRET outside the vault\n")
    (root / "leak.md").symlink_to(secret)
    # the bulk scan does not enumerate the escaping symlink,
    names = {p.relative_to(root).as_posix() for p in server.iter_markdown(root)}
    assert "leak.md" not in names
    # so search cannot leak the target's content,
    assert server.search_notes(root, "TOP SECRET", 10, UTC) == []
    # and the note tool blocks the same path (it always did).
    assert server.safe_join(root, "leak.md") is None


def test_note_tool_returns_an_error_for_an_unresolvable_path(tmp_path, monkeypatch) -> None:
    root = _vault(tmp_path)
    monkeypatch.setattr(server, "VAULT_PATH", str(root))
    monkeypatch.setattr(server, "SUBDIR", "")
    # A null byte makes resolve() raise; the tool must return an error, not crash.
    result = asyncio.run(server.note("\x00.md"))
    assert "error" in result
