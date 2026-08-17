"""Tests for the bash tool's defense-in-depth guardrails."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from okti.tools.bash import _is_denied, _resolve_cwd, run_command


# ---------------------------------------------------------------------------
# Denylist
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "rm -rf /",
    "rm -rf /*",
    "rm -rf ~",
    "rm -rf $HOME",
    "rm -Rf /",
    ":(){ :|:& };:",
    "mkfs.ext4 /dev/sda1",
    "dd if=/dev/zero of=/dev/sda bs=1M",
    "chmod -R 777 /",
    "shutdown -h now",
    "reboot",
    "cat /dev/zero > /dev/sda",
])
def test_denylist_rejects(command):
    assert _is_denied(command) is not None, f"should reject: {command}"


@pytest.mark.parametrize("command", [
    "rm -rf ./build",
    "rm -rf node_modules",
    "ls -la /etc",
    "git status",
    "echo hello",
    "chmod +x script.sh",
    "chmod 755 file.py",
    "grep -rn TODO src/",
])
def test_denylist_allows_normal(command):
    assert _is_denied(command) is None, f"should allow: {command}"


@pytest.mark.asyncio
async def test_run_command_refuses_denied():
    result = await run_command("rm -rf /")
    assert "refused by safety denylist" in result


# ---------------------------------------------------------------------------
# Workspace escape
# ---------------------------------------------------------------------------

def test_resolve_cwd_within_workspace(tmp_path):
    (tmp_path / "sub").mkdir()
    resolved = _resolve_cwd(tmp_path, "sub")
    assert resolved is not None
    assert resolved == (tmp_path / "sub").resolve()


def test_resolve_cwd_none_returns_workspace(tmp_path):
    resolved = _resolve_cwd(tmp_path, None)
    assert resolved == tmp_path


def test_resolve_cwd_rejects_escape(tmp_path):
    resolved = _resolve_cwd(tmp_path, "../../../etc")
    assert resolved is None


def test_resolve_cwd_rejects_absolute_outside(tmp_path):
    resolved = _resolve_cwd(tmp_path, "/etc")
    assert resolved is None


@pytest.mark.asyncio
async def test_run_command_refuses_escape(tmp_path, monkeypatch):
    monkeypatch.setenv("OKTI_WORKSPACE", str(tmp_path))
    result = await run_command("echo hi", working_directory="../..")
    assert "escapes workspace" in result


# ---------------------------------------------------------------------------
# Timeout & basic execution (smoke)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_command_smoke(tmp_path, monkeypatch):
    monkeypatch.setenv("OKTI_WORKSPACE", str(tmp_path))
    result = await run_command("echo hello-okti")
    assert "hello-okti" in result


@pytest.mark.asyncio
async def test_run_command_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv("OKTI_WORKSPACE", str(tmp_path))
    result = await run_command("sleep 5", timeout=1)
    assert "timed out" in result
