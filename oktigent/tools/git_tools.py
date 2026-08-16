"""Git tools — status, diff, commit, log, branch, and more.

Provides the agent with full git workflow capabilities.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

from oktigent.tools.registry import ToolDef, ToolRegistry


def _get_workspace() -> Path:
    return Path(os.environ.get("OKTIGENT_WORKSPACE", os.getcwd()))


def _run_git_sync(*args: str, timeout: int = 30) -> tuple[int, str, str]:
    """Run a git command synchronously and return (exit_code, stdout, stderr)."""
    ws = _get_workspace()
    try:
        result = subprocess.run(
            ["git"] + list(args),
            cwd=str(ws),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError:
        return -1, "", "git not found in PATH"
    except subprocess.TimeoutExpired:
        return -1, "", f"git command timed out after {timeout}s"


async def _run_git(*args: str, timeout: int = 30) -> tuple[int, str, str]:
    """Run a git command in a worker thread and return (exit_code, stdout, stderr)."""
    return await asyncio.to_thread(_run_git_sync, *args, timeout=timeout)


async def git_status() -> str:
    """Show working tree status."""
    code, out, err = await _run_git("status", "--short")
    if code != 0:
        return f"Error: {err}"
    if not out:
        return "Working tree clean — no changes."
    return f"Changes:\n{out}"


async def git_diff(path: str | None = None, staged: bool = False) -> str:
    """Show file changes."""
    args = ["diff"]
    if staged:
        args.append("--cached")
    if path:
        args.extend(["--", path])
    code, out, err = await _run_git(*args)
    if code != 0:
        return f"Error: {err}"
    if not out:
        return "No changes to diff."
    # Truncate if too large
    if len(out) > 30000:
        lines = out.splitlines()
        out = "\n".join(lines[:500])
        out += f"\n\n... ({len(lines)} lines total, showing first 500)"
    return out


async def git_log(count: int = 10) -> str:
    """Show recent commit log."""
    code, out, err = await _run_git("log", "--oneline", f"-{count}")
    if code != 0:
        return f"Error: {err}"
    if not out:
        return "No commits yet."
    return f"Recent commits:\n{out}"


async def git_add(files: str = ".") -> str:
    """Stage files for commit."""
    file_list = [f.strip() for f in files.split(",") if f.strip()]
    if not file_list:
        file_list = ["."]
    code, out, err = await _run_git("add", *file_list)
    if code != 0:
        return f"Error: {err}"
    return f"Staged: {files}"


async def git_commit(message: str) -> str:
    """Create a commit with the given message."""
    if not message:
        return "Error: commit message cannot be empty"
    code, out, err = await _run_git("commit", "-m", message)
    if code != 0:
        return f"Error: {err}\n{out}"
    return f"Committed: {message}\n{out}"


async def git_push(remote: str = "origin", branch: str = "") -> str:
    """Push to remote."""
    args = ["push", remote]
    if branch:
        args.append(branch)
    code, out, err = await _run_git(*args, timeout=60)
    if code != 0:
        return f"Error: {err}"
    return f"Pushed to {remote}\n{out}"


async def git_pull(remote: str = "origin", branch: str = "") -> str:
    """Pull from remote."""
    args = ["pull", remote]
    if branch:
        args.append(branch)
    code, out, err = await _run_git(*args, timeout=60)
    if code != 0:
        return f"Error: {err}"
    return f"Pulled from {remote}\n{out}"


async def git_branch() -> str:
    """List branches."""
    code, out, err = await _run_git("branch", "-a")
    if code != 0:
        return f"Error: {err}"
    return f"Branches:\n{out}"


async def git_checkout(branch: str) -> str:
    """Switch to a branch."""
    code, out, err = await _run_git("checkout", branch)
    if code != 0:
        return f"Error: {err}"
    return f"Switched to branch: {branch}\n{out}"


async def git_create_branch(name: str) -> str:
    """Create a new branch."""
    code, out, err = await _run_git("checkout", "-b", name)
    if code != 0:
        return f"Error: {err}"
    return f"Created and switched to branch: {name}"


async def git_stash(message: str = "") -> str:
    """Stash changes."""
    args = ["stash"]
    if message:
        args.extend(["push", "-m", message])
    code, out, err = await _run_git(*args)
    if code != 0:
        return f"Error: {err}"
    return out or "Changes stashed."


async def git_stash_pop() -> str:
    """Pop the latest stash."""
    code, out, err = await _run_git("stash", "pop")
    if code != 0:
        return f"Error: {err}"
    return out or "Stash popped."


async def git_blame(path: str) -> str:
    """Show who last modified each line of a file."""
    code, out, err = await _run_git("blame", "--porcelain", path)
    if code != 0:
        return f"Error: {err}"
    # Parse porcelain format into readable output
    lines = out.splitlines()
    result = []
    author = ""
    for line in lines:
        if line.startswith("\t"):
            result.append(f"{author}: {line.strip()}")
        elif "author " in line and not line.startswith("author"):
            author = line.split("author ", 1)[-1]
    if not result:
        return f"Blame for {path}:\n{out[:5000]}"
    return f"Blame for {path}:\n" + "\n".join(result[:200])


async def git_ignore_add(pattern: str) -> str:
    """Add a pattern to .gitignore."""
    ws = _get_workspace()
    gitignore = ws / ".gitignore"
    content = ""
    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8")

    if pattern in content:
        return f"Pattern already in .gitignore: {pattern}"

    content = content.rstrip() + f"\n{pattern}\n"
    gitignore.write_text(content, encoding="utf-8")
    return f"Added to .gitignore: {pattern}"


async def git_remote_url() -> str:
    """Show the remote URL."""
    code, out, err = await _run_git("remote", "get-url", "origin")
    if code != 0:
        return f"Error: {err}"
    return f"Remote URL: {out}"


async def git_status_detailed() -> str:
    """Show detailed status with branch info."""
    parts = []

    # Branch
    code, out, _ = await _run_git("branch", "--show-current")
    if code == 0 and out:
        parts.append(f"Branch: {out}")

    # Remote tracking
    code, out, _ = await _run_git("rev-parse", "--abbrev-ref", "@{upstream}")
    if code == 0 and out:
        parts.append(f"Tracking: {out}")

    # Ahead/behind
    code, out, _ = await _run_git("rev-list", "--left-right", "--count", "HEAD...@{upstream}")
    if code == 0 and out:
        parts.append(f"Ahead/Behind: {out}")

    # Staged
    code, out, _ = await _run_git("diff", "--cached", "--stat")
    if code == 0 and out:
        parts.append(f"Staged:\n{out}")

    # Unstaged
    code, out, _ = await _run_git("diff", "--stat")
    if code == 0 and out:
        parts.append(f"Unstaged:\n{out}")

    # Untracked
    code, out, _ = await _run_git("ls-files", "--others", "--exclude-standard")
    if code == 0 and out:
        count = len(out.splitlines())
        parts.append(f"Untracked: {count} files")

    if not parts:
        return "No git repository found."
    return "\n".join(parts)


def register_git_tools(registry: ToolRegistry) -> None:
    """Register all git tools."""
    registry.register(ToolDef(
        name="git_status",
        description="Show git working tree status (short format).",
        parameters={"type": "object", "properties": {}},
        handler=git_status,
        risk_level="low",
    ))

    registry.register(ToolDef(
        name="git_diff",
        description="Show file changes. Use path for specific file, staged=true for staged changes.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Specific file path (optional)"},
                "staged": {"type": "boolean", "description": "Show staged changes (default: false)"},
            },
        },
        handler=git_diff,
        risk_level="low",
    ))

    registry.register(ToolDef(
        name="git_log",
        description="Show recent commit log.",
        parameters={
            "type": "object",
            "properties": {
                "count": {"type": "integer", "description": "Number of commits to show (default: 10)"},
            },
        },
        handler=git_log,
        risk_level="low",
    ))

    registry.register(ToolDef(
        name="git_add",
        description="Stage files for commit. Comma-separated file paths, or '.' for all.",
        parameters={
            "type": "object",
            "properties": {
                "files": {"type": "string", "description": "Comma-separated files or '.' for all (default: '.')"},
            },
        },
        handler=git_add,
        risk_level="medium",
    ))

    registry.register(ToolDef(
        name="git_commit",
        description="Create a git commit. Stage files first with git_add.",
        parameters={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Commit message"},
            },
            "required": ["message"],
        },
        handler=git_commit,
        risk_level="medium",
    ))

    registry.register(ToolDef(
        name="git_push",
        description="Push commits to remote.",
        parameters={
            "type": "object",
            "properties": {
                "remote": {"type": "string", "description": "Remote name (default: origin)"},
                "branch": {"type": "string", "description": "Branch name (default: current)"},
            },
        },
        handler=git_push,
        risk_level="high",
    ))

    registry.register(ToolDef(
        name="git_pull",
        description="Pull from remote.",
        parameters={
            "type": "object",
            "properties": {
                "remote": {"type": "string", "description": "Remote name (default: origin)"},
                "branch": {"type": "string", "description": "Branch name (default: current)"},
            },
        },
        handler=git_pull,
        risk_level="medium",
    ))

    registry.register(ToolDef(
        name="git_branch",
        description="List all branches.",
        parameters={"type": "object", "properties": {}},
        handler=git_branch,
        risk_level="low",
    ))

    registry.register(ToolDef(
        name="git_checkout",
        description="Switch to a branch.",
        parameters={
            "type": "object",
            "properties": {
                "branch": {"type": "string", "description": "Branch name to switch to"},
            },
            "required": ["branch"],
        },
        handler=git_checkout,
        risk_level="medium",
    ))

    registry.register(ToolDef(
        name="git_create_branch",
        description="Create and switch to a new branch.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "New branch name"},
            },
            "required": ["name"],
        },
        handler=git_create_branch,
        risk_level="medium",
    ))

    registry.register(ToolDef(
        name="git_stash",
        description="Stash current changes.",
        parameters={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Optional stash message"},
            },
        },
        handler=git_stash,
        risk_level="medium",
    ))

    registry.register(ToolDef(
        name="git_stash_pop",
        description="Pop the most recent stash.",
        parameters={"type": "object", "properties": {}},
        handler=git_stash_pop,
        risk_level="medium",
    ))

    registry.register(ToolDef(
        name="git_ignore_add",
        description="Add a pattern to .gitignore.",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Pattern to add (e.g. '*.pyc', 'dist/')"},
            },
            "required": ["pattern"],
        },
        handler=git_ignore_add,
        risk_level="low",
    ))

    registry.register(ToolDef(
        name="git_status_detailed",
        description="Show detailed git status with branch info, staged/unstaged/untracked counts.",
        parameters={"type": "object", "properties": {}},
        handler=git_status_detailed,
        risk_level="low",
    ))

    registry.register(ToolDef(
        name="git_blame",
        description="Show who last modified each line of a file.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to blame"},
                "line_start": {"type": "integer", "description": "Start line (optional)"},
                "line_end": {"type": "integer", "description": "End line (optional)"},
            },
            "required": ["path"],
        },
        handler=git_blame,
        risk_level="low",
    ))

    registry.register(ToolDef(
        name="git_remote_url",
        description="Show the remote URL of the current repository.",
        parameters={"type": "object", "properties": {}},
        handler=git_remote_url,
        risk_level="low",
    ))
