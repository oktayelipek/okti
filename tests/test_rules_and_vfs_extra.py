"""Additional coverage for agent.rules and tools.vfs (schemes + edge cases)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from okti.agent.rules import load_universal_rules, render_rules_markdown
from okti.tools.vfs import (
    VFS_SCHEMES,
    is_virtual_uri,
    resolve_virtual_uri,
)

# ---------------------------------------------------------------------------
# rules.py — cover cursor MDC, okti/rules, okti/memory branches
# ---------------------------------------------------------------------------


def test_cursor_mdc_rules_loaded(tmp_path: Path):
    mdc_dir = tmp_path / ".cursor" / "rules"
    mdc_dir.mkdir(parents=True)
    (mdc_dir / "style.mdc").write_text("Use tabs.", encoding="utf-8")
    (mdc_dir / "naming.md").write_text("camelCase for vars.", encoding="utf-8")
    (mdc_dir / "ignored.txt").write_text("nope", encoding="utf-8")

    rules = load_universal_rules(workspace=tmp_path)
    types = [r.source_type for r in rules]
    assert types.count("cursor_mdc") == 2
    contents = {r.content for r in rules if r.source_type == "cursor_mdc"}
    assert "Use tabs." in contents
    assert "camelCase for vars." in contents


def test_okti_local_rules_and_memory_loaded(tmp_path: Path):
    okti_dir = tmp_path / ".okti"
    (okti_dir / "rules").mkdir(parents=True)
    (okti_dir / "rules" / "a.md").write_text("Rule A", encoding="utf-8")
    (okti_dir / "rules" / "b.md").write_text("Rule B", encoding="utf-8")
    (okti_dir / "memory.md").write_text("Project memory content.", encoding="utf-8")

    rules = load_universal_rules(workspace=tmp_path)
    types = [r.source_type for r in rules]
    assert types.count("okti") == 2
    assert "okti_memory" in types
    mem = next(r for r in rules if r.source_type == "okti_memory")
    assert mem.content == "Project memory content."


def test_empty_rule_files_are_skipped(tmp_path: Path):
    (tmp_path / ".cursorrules").write_text("   \n\n", encoding="utf-8")
    (tmp_path / ".clinerules").write_text("", encoding="utf-8")
    rules = load_universal_rules(workspace=tmp_path)
    assert rules == []


def test_gemini_and_claude_standard_files(tmp_path: Path):
    (tmp_path / "CLAUDE.md").write_text("Claude standards.", encoding="utf-8")
    (tmp_path / "GEMINI.md").write_text("Gemini standards.", encoding="utf-8")
    rules = load_universal_rules(workspace=tmp_path)
    types = {r.source_type for r in rules}
    assert {"claude", "gemini"}.issubset(types)


def test_render_rules_markdown_empty_message():
    assert render_rules_markdown([]) == "No external rules found in workspace."


def test_render_rules_markdown_includes_counts_and_titles(tmp_path: Path):
    (tmp_path / ".cursorrules").write_text("R", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("R2", encoding="utf-8")
    rules = load_universal_rules(workspace=tmp_path)
    out = render_rules_markdown(rules)
    assert "2 rule file(s)" in out
    assert "Cursor Rules" in out
    assert "AGENTS.md" in out


# ---------------------------------------------------------------------------
# vfs.py — cover unknown scheme, non-string uri, skill://, conflict://
# ---------------------------------------------------------------------------


def test_is_virtual_uri_rejects_non_strings():
    assert is_virtual_uri(None) is False  # type: ignore[arg-type]
    assert is_virtual_uri(123) is False  # type: ignore[arg-type]
    assert is_virtual_uri([]) is False  # type: ignore[arg-type]


def test_is_virtual_uri_matches_all_declared_schemes():
    for scheme in VFS_SCHEMES:
        assert is_virtual_uri(scheme + "anything")


async def test_resolve_unknown_scheme_returns_message():
    out = await resolve_virtual_uri("unknown://foo")
    assert "Unknown virtual URI scheme" in out


async def test_skill_uri_missing_target_gives_usage_hint():
    out = await resolve_virtual_uri("skill://")
    assert "Usage" in out


async def test_skill_uri_loads_from_cwd_agents(tmp_path, monkeypatch):
    skill_dir = tmp_path / ".agents" / "skills" / "my-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("How to skill.", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    out = await resolve_virtual_uri("skill://my-skill")
    assert "Skill: my-skill" in out
    assert "How to skill." in out


async def test_skill_uri_not_found(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Redirect $HOME so the global fallback path also misses
    monkeypatch.setenv("HOME", str(tmp_path))
    out = await resolve_virtual_uri("skill://ghost")
    assert "not found" in out


async def test_conflict_uri_when_no_git_repo(tmp_path, monkeypatch):
    # Point cwd at a directory without a git repo — git returns nonzero
    monkeypatch.chdir(tmp_path)
    out = await resolve_virtual_uri("conflict://list")
    # Either "no conflicts" (if git returned empty) or a failure message
    assert isinstance(out, str)
    assert out  # non-empty


async def test_conflict_uri_reports_unmerged_files(monkeypatch, tmp_path):
    # Simulate git returning two unmerged files
    class FakeCompleted:
        returncode = 0
        stdout = "a.py\nb.py\n"
        stderr = ""

    def fake_run(*_a, **_kw):
        return FakeCompleted()

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.chdir(tmp_path)

    out = await resolve_virtual_uri("conflict://list")
    assert "Active Merge Conflicts (2 files)" in out
    assert "`a.py`" in out
    assert "`b.py`" in out


async def test_conflict_uri_notes_conflict_blocks_in_files(monkeypatch, tmp_path):
    conflict_content = (
        "line above\n"
        "<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> branch\n"
        "line below\n"
    )
    (tmp_path / "c.py").write_text(conflict_content, encoding="utf-8")

    class FakeCompleted:
        returncode = 0
        stdout = "c.py\n"
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *_a, **_kw: FakeCompleted())
    monkeypatch.chdir(tmp_path)

    out = await resolve_virtual_uri("conflict://list")
    assert "Found 1 conflict block(s)" in out


async def test_diff_uri_error_path(monkeypatch):
    class FakeCompleted:
        returncode = 1
        stdout = ""
        stderr = "not a git repo"

    monkeypatch.setattr(subprocess, "run", lambda *_a, **_kw: FakeCompleted())
    out = await resolve_virtual_uri("diff://staged")
    assert "Git diff error" in out


async def test_diff_uri_empty_output(monkeypatch):
    class FakeCompleted:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *_a, **_kw: FakeCompleted())
    out = await resolve_virtual_uri("diff://staged")
    assert "No changes found" in out


async def test_git_uri_log_and_branch_paths(monkeypatch):
    captured = []

    class FakeCompleted:
        returncode = 0
        stdout = "abc123 msg"
        stderr = ""

    def fake_run(cmd, **_kw):
        captured.append(cmd)
        return FakeCompleted()

    monkeypatch.setattr(subprocess, "run", fake_run)

    await resolve_virtual_uri("git://log")
    await resolve_virtual_uri("git://branch")
    assert captured[0][:2] == ["git", "log"]
    assert captured[1][:2] == ["git", "branch"]


async def test_git_uri_error_path(monkeypatch):
    class FakeCompleted:
        returncode = 1
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr(subprocess, "run", lambda *_a, **_kw: FakeCompleted())
    out = await resolve_virtual_uri("git://status")
    assert "Git error" in out


@pytest.mark.parametrize("uri,expected_scheme_prefix", [
    ("rules://cursor", "rule"),
    ("skills://x", "skill"),
])
def test_alias_schemes_are_recognized(uri, expected_scheme_prefix):
    assert is_virtual_uri(uri)
