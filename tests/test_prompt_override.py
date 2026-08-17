"""Tests for user-supplied prompt overrides and the /prompt / --print-prompt paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from okti.agent.prompts import (
    _UNIVERSAL_OVERRIDE,
    _find_prompt,
    describe_prompt,
    load_system_prompt,
)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("OKTI_WORKSPACE", str(tmp_path))
    return tmp_path


def _write(root: Path, filename: str, content: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / filename
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Search order
# ---------------------------------------------------------------------------

def test_workspace_beats_user_config(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    user_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: user_home)

    _write(ws / ".okti" / "prompts", "openai.md", "workspace wins")
    _write(user_home / ".config" / "okti" / "prompts", "openai.md", "user loses")

    content, source = _find_prompt("openai", workspace_dir=ws)
    assert content == "workspace wins"
    assert "workspace" in source


def test_user_config_beats_bundled_defaults(tmp_path, monkeypatch):
    user_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: user_home)

    _write(user_home / ".config" / "okti" / "prompts", "openai.md", "user override")

    content, source = _find_prompt("openai", workspace_dir=None)
    assert content == "user override"
    assert "user config" in source


def test_universal_override_used_when_provider_specific_missing(tmp_path, monkeypatch):
    user_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: user_home)

    # No claude.md, only okti.md
    _write(user_home / ".config" / "okti" / "prompts", _UNIVERSAL_OVERRIDE, "universal")

    content, source = _find_prompt("anthropic", workspace_dir=None)
    assert content == "universal"
    assert _UNIVERSAL_OVERRIDE in source


def test_provider_file_beats_universal_in_same_dir(tmp_path, monkeypatch):
    user_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: user_home)

    prompt_dir = user_home / ".config" / "okti" / "prompts"
    _write(prompt_dir, "claude.md", "provider-specific")
    _write(prompt_dir, _UNIVERSAL_OVERRIDE, "universal")

    content, source = _find_prompt("anthropic", workspace_dir=None)
    assert content == "provider-specific"


def test_empty_override_file_ignored(tmp_path, monkeypatch):
    user_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: user_home)

    _write(user_home / ".config" / "okti" / "prompts", "openai.md", "   \n  ")

    content, source = _find_prompt("openai", workspace_dir=None)
    # Empty override is skipped; falls through to bundled defaults if any,
    # otherwise returns (None, "")
    if content:
        assert "bundled" in source
    else:
        assert content is None


# ---------------------------------------------------------------------------
# describe_prompt reporting
# ---------------------------------------------------------------------------

def test_describe_marks_the_active_file(tmp_path, monkeypatch):
    user_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: user_home)
    _write(user_home / ".config" / "okti" / "prompts", "openai.md", "hello")

    report = describe_prompt(provider_id="openai", workspace_dir=None)
    assert "ACTIVE" in report
    active_line = next(line for line in report.splitlines() if "ACTIVE" in line)
    assert "openai.md" in active_line
    assert "user config" in active_line


def test_describe_labels_shadowed_files(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    user_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: user_home)

    _write(ws / ".okti" / "prompts", "openai.md", "workspace wins")
    _write(user_home / ".config" / "okti" / "prompts", "openai.md", "shadowed")

    report = describe_prompt(provider_id="openai", workspace_dir=ws)
    assert "ACTIVE" in report
    assert "shadowed" in report


def test_describe_notes_no_overrides(tmp_path, monkeypatch):
    user_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: user_home)
    # Also point search away from repo's bundled prompts
    monkeypatch.chdir(tmp_path)

    report = describe_prompt(provider_id="unknown-provider", workspace_dir=tmp_path)
    # Either the bundled default matched (local.md) or nothing did — both fine
    assert "System prompt for provider" in report


# ---------------------------------------------------------------------------
# End-to-end via load_system_prompt
# ---------------------------------------------------------------------------

def test_load_system_prompt_uses_override(tmp_path, monkeypatch):
    user_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: user_home)
    _write(user_home / ".config" / "okti" / "prompts", "openai.md",
           "OVERRIDE PROMPT: be terse.")

    resolved = load_system_prompt(provider_id="openai", workspace_dir=None)
    assert resolved.startswith("OVERRIDE PROMPT: be terse.")
