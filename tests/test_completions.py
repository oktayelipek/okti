"""Tests for shell completion script emission."""

from __future__ import annotations

import io
from contextlib import redirect_stdout

import pytest

from okti.completions import SUPPORTED_SHELLS, get_completion_script


@pytest.mark.parametrize("shell", SUPPORTED_SHELLS)
def test_get_completion_script_supported_shells(shell):
    script = get_completion_script(shell)
    assert isinstance(script, str) and script.strip()
    # Every script must reference the CLI name so the shell wires it up.
    assert "okti" in script


def test_bash_script_registers_complete_directive():
    out = get_completion_script("bash")
    assert "complete -F _okti_complete okti" in out
    # Long options should appear
    assert "--yolo" in out
    assert "--install-completions" in out
    # Config path must accept file completion
    assert "compgen -f" in out


def test_zsh_script_has_compdef_header_and_options():
    out = get_completion_script("zsh")
    assert out.startswith("#compdef okti")
    assert "_arguments" in out
    assert "--yolo" in out


def test_fish_script_uses_complete_command_per_option():
    out = get_completion_script("fish")
    lines = [ln for ln in out.splitlines() if ln.strip() and not ln.startswith("#")]
    assert all(ln.startswith("complete -c okti") for ln in lines)
    # Fish uses `-l yolo` (long-option name without leading dashes)
    assert any("-l yolo" in ln for ln in lines)
    assert any("-l install-completions" in ln for ln in lines)


def test_unknown_shell_raises():
    with pytest.raises(ValueError) as exc:
        get_completion_script("powershell")
    assert "Unsupported shell" in str(exc.value)


def test_shell_names_are_case_insensitive():
    assert get_completion_script("BASH") == get_completion_script("bash")


def test_cli_flag_emits_script_and_exits(monkeypatch):
    from okti import __main__ as m

    buf = io.StringIO()
    with redirect_stdout(buf):
        m.main(["--install-completions", "bash"])
    out = buf.getvalue()
    assert "complete -F _okti_complete okti" in out
