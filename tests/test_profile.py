"""Tests for cross-session user profile (remember_this / forget_this)."""

from __future__ import annotations

from pathlib import Path

import pytest

from okti.context.profile import (
    _slugify_category,
    append_fact,
    build_profile_prompt,
    forget_facts,
    forget_this,
    load_user_profile,
    remember_this,
)


@pytest.fixture(autouse=True)
def _isolate_profile(tmp_path: Path, monkeypatch):
    """Point every test at a fresh profile file via OKTI_PROFILE_PATH."""
    path = tmp_path / "profile.md"
    monkeypatch.setenv("OKTI_PROFILE_PATH", str(path))
    yield path


# ---------------------------------------------------------------------------
# Load semantics
# ---------------------------------------------------------------------------

def test_load_missing_returns_empty():
    assert load_user_profile() == ""


def test_load_reads_file(_isolate_profile: Path):
    _isolate_profile.write_text("## Preferences\n- (2026-01-01) uses tabs\n")
    assert "tabs" in load_user_profile()


def test_load_truncates_oversized_file(_isolate_profile: Path):
    huge = "- x\n" * 30000  # >100 KB
    _isolate_profile.write_text(huge)
    text = load_user_profile()
    assert "[truncated" in text
    assert len(text) < 200_000


def test_build_profile_prompt_empty_in_empty_out():
    assert build_profile_prompt("") == ""


def test_build_profile_prompt_wraps_in_tags():
    out = build_profile_prompt("hello")
    assert out.startswith("<user_profile>")
    assert out.endswith("</user_profile>")
    assert "hello" in out


# ---------------------------------------------------------------------------
# Category slugification
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("preferences", "Preferences"),
    ("  code  style  ", "Code Style"),
    ("", "General"),
    (None, "General"),
])
def test_slugify_category(raw, expected):
    assert _slugify_category(raw) == expected


# ---------------------------------------------------------------------------
# append_fact
# ---------------------------------------------------------------------------

def test_append_creates_file_and_category(_isolate_profile: Path):
    result = append_fact("uses tabs", category="Preferences")
    assert "Remembered under Preferences" in result

    text = _isolate_profile.read_text()
    assert "## Preferences" in text
    assert "uses tabs" in text


def test_append_reuses_existing_category(_isolate_profile: Path):
    append_fact("uses tabs", category="Preferences")
    append_fact("hates semicolons", category="Preferences")

    text = _isolate_profile.read_text()
    # Only one header
    assert text.count("## Preferences") == 1
    assert "uses tabs" in text
    assert "hates semicolons" in text


def test_append_creates_second_category(_isolate_profile: Path):
    append_fact("uses tabs", category="Preferences")
    append_fact("Postgres", category="Stack")

    text = _isolate_profile.read_text()
    assert "## Preferences" in text
    assert "## Stack" in text


def test_append_empty_fact_noop(_isolate_profile: Path):
    result = append_fact("   ", category="Preferences")
    assert "empty" in result.lower()
    assert not _isolate_profile.exists()


def test_append_bullets_land_in_the_right_section(_isolate_profile: Path):
    append_fact("a", category="Alpha")
    append_fact("b", category="Beta")
    append_fact("a2", category="Alpha")

    text = _isolate_profile.read_text()
    alpha_idx = text.index("## Alpha")
    beta_idx = text.index("## Beta")
    a2_idx = text.index("a2")
    # The a2 bullet must sit inside the Alpha block (before the Beta header)
    assert alpha_idx < a2_idx < beta_idx


# ---------------------------------------------------------------------------
# forget_facts
# ---------------------------------------------------------------------------

def test_forget_empty_needle():
    assert "non-empty" in forget_facts("")


def test_forget_from_empty_profile(_isolate_profile: Path):
    assert "empty" in forget_facts("tabs").lower()


def test_forget_removes_matching_bullets(_isolate_profile: Path):
    append_fact("uses tabs", category="Preferences")
    append_fact("hates semicolons", category="Preferences")

    msg = forget_facts("tabs")
    assert "Forgot 1" in msg

    text = _isolate_profile.read_text()
    assert "uses tabs" not in text
    assert "hates semicolons" in text


def test_forget_case_insensitive(_isolate_profile: Path):
    append_fact("uses TABS", category="Preferences")
    forget_facts("tabs")
    assert "TABS" not in _isolate_profile.read_text()


def test_forget_cleans_up_empty_categories(_isolate_profile: Path):
    append_fact("only entry", category="Solo")
    append_fact("keeper", category="Other")
    forget_facts("only entry")

    text = _isolate_profile.read_text()
    assert "## Solo" not in text
    assert "## Other" in text
    assert "keeper" in text


# ---------------------------------------------------------------------------
# Async tool wrappers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_remember_this_tool(_isolate_profile: Path):
    result = await remember_this("uses tabs", category="Preferences")
    assert "Remembered under Preferences" in result
    assert "uses tabs" in _isolate_profile.read_text()


@pytest.mark.asyncio
async def test_forget_this_tool(_isolate_profile: Path):
    await remember_this("uses tabs")
    result = await forget_this("tabs")
    assert "Forgot 1" in result


# ---------------------------------------------------------------------------
# Integration into system prompt
# ---------------------------------------------------------------------------

def test_load_system_prompt_includes_profile(_isolate_profile: Path):
    append_fact("prefers minimal explanations", category="Style")
    from okti.agent.prompts import load_system_prompt
    prompt = load_system_prompt(provider_id="ollama")
    assert "<user_profile>" in prompt
    assert "prefers minimal explanations" in prompt
