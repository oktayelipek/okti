"""Tests for prompt loading and memory integration."""

from oktigent.agent.prompts import load_system_prompt


def test_load_system_prompt_anthropic():
    prompt = load_system_prompt("anthropic")
    assert "Claude" in prompt or "oktigent" in prompt
    assert "tools" in prompt.lower() or "edit_file" in prompt


def test_load_system_prompt_openai():
    prompt = load_system_prompt("openai")
    assert "oktigent" in prompt


def test_load_system_prompt_fallback():
    prompt = load_system_prompt("unknown_provider")
    assert "oktigent" in prompt


def test_load_system_prompt_with_workspace_memory(tmp_path):
    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text("Custom rule: Always use Python 3.12 syntax.")

    prompt = load_system_prompt("anthropic", workspace_dir=tmp_path)
    assert "Custom rule: Always use Python 3.12 syntax" in prompt
