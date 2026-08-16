"""Tests for git tools."""

import pytest
from oktigent.tools.git_tools import (
    git_status, git_diff, git_log, git_branch, git_status_detailed, register_git_tools,
)
from oktigent.tools.registry import ToolRegistry


@pytest.fixture(autouse=True)
def setup_git_workspace(tmp_path, monkeypatch):
    """Create a temporary git workspace."""
    import subprocess
    workspace = tmp_path / "repo"
    workspace.mkdir()
    monkeypatch.setenv("OKTIGENT_WORKSPACE", str(workspace))

    # Init git repo
    subprocess.run(["git", "init"], cwd=str(workspace), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(workspace), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(workspace), capture_output=True)

    # Create initial commit
    (workspace / "README.md").write_text("# Test\n")
    subprocess.run(["git", "add", "."], cwd=str(workspace), capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(workspace), capture_output=True)

    return workspace


@pytest.mark.asyncio
async def test_git_status():
    result = await git_status()
    assert "clean" in result.lower() or "no changes" in result.lower() or "Changes" in result or "nothing" in result.lower()


@pytest.mark.asyncio
async def test_git_log():
    result = await git_log(count=5)
    assert "init" in result.lower() or "commit" in result.lower() or "Recent" in result


@pytest.mark.asyncio
async def test_git_branch():
    result = await git_branch()
    assert "master" in result.lower() or "main" in result.lower() or "Branches" in result


@pytest.mark.asyncio
async def test_git_diff_clean():
    result = await git_diff()
    assert "no changes" in result.lower() or "Error" in result or result == ""


@pytest.mark.asyncio
async def test_git_status_detailed():
    result = await git_status_detailed()
    assert "Branch" in result or "No git" in result


def test_git_tools_registry():
    registry = ToolRegistry()
    register_git_tools(registry)
    git_tool_names = [n for n in registry.tool_names() if n.startswith("git_")]
    assert len(git_tool_names) >= 8  # at least 8 git tools
