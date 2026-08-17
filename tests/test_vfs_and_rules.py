"""Tests for VFS virtual URI schemes and Universal Rules Engine."""

from pathlib import Path

import pytest

from okti.agent.rules import load_universal_rules, render_rules_markdown
from okti.tools.files import read_file
from okti.tools.vfs import is_virtual_uri, resolve_virtual_uri


def test_is_virtual_uri():
    assert is_virtual_uri("diff://")
    assert is_virtual_uri("diff://staged")
    assert is_virtual_uri("git://status")
    assert is_virtual_uri("rule://all")
    assert is_virtual_uri("skill://test")
    assert is_virtual_uri("conflict://list")
    assert not is_virtual_uri("src/main.py")
    assert not is_virtual_uri("C:/Users/test/file.txt")


def test_load_universal_rules(tmp_path: Path):
    # Setup mock rule files
    (tmp_path / ".cursorrules").write_text("Use TypeScript strict mode.", encoding="utf-8")
    (tmp_path / ".clinerules").write_text("Always run tests before committing.", encoding="utf-8")

    gh_dir = tmp_path / ".github"
    gh_dir.mkdir()
    (gh_dir / "copilot-instructions.md").write_text("Prefer functional patterns.", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("Agents must follow project architecture.", encoding="utf-8")

    rules = load_universal_rules(workspace=tmp_path)
    assert len(rules) == 4

    types = {r.source_type for r in rules}
    assert "cursor" in types
    assert "cline" in types
    assert "copilot" in types
    assert "agents" in types

    rendered = render_rules_markdown(rules)
    assert "Cursor Rules" in rendered
    assert "Cline Rules" in rendered
    assert "copilot-instructions.md" in rendered
    assert "AGENTS.md" in rendered


@pytest.mark.asyncio
async def test_vfs_rule_uri_resolution(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OKTI_WORKSPACE", str(tmp_path))
    (tmp_path / ".cursorrules").write_text("Cursor specific rule.", encoding="utf-8")

    out_all = await resolve_virtual_uri("rule://all")
    assert "Cursor Rules" in out_all
    assert "Cursor specific rule." in out_all

    out_cursor = await resolve_virtual_uri("rule://cursor")
    assert "Cursor Rules" in out_cursor

    out_missing = await resolve_virtual_uri("rule://nonexistent")
    assert "No rules found" in out_missing


@pytest.mark.asyncio
async def test_read_file_transparent_vfs_dispatch(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OKTI_WORKSPACE", str(tmp_path))
    (tmp_path / "AGENTS.md").write_text("Test agent guidelines.", encoding="utf-8")

    # read_file transparently resolves rule:// URI
    res = await read_file("rule://all")
    assert "AGENTS.md Project Standards" in res
    assert "Test agent guidelines." in res


@pytest.mark.asyncio
async def test_vfs_diff_and_git_uri():
    # Calling diff:// and git:// should return formatted markdown strings
    diff_out = await resolve_virtual_uri("diff://")
    assert isinstance(diff_out, str)

    git_out = await resolve_virtual_uri("git://status")
    assert isinstance(git_out, str)
    assert "Git Output" in git_out or "Git error" in git_out
