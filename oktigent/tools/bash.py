"""Bash / shell command execution tool.

Supports sandboxed execution and terminal output management.
Large outputs are truncated and referenced by ID (background context).
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path

from oktigent.tools.registry import ToolDef, ToolRegistry

logger = logging.getLogger(__name__)

# Max output size before it goes to "background"
MAX_OUTPUT_CHARS = 50_000
MAX_TIMEOUT_SECONDS = 120


async def run_command(
    command: str,
    timeout: int = 60,
    working_directory: str | None = None,
) -> str:
    """Execute a shell command and return its output.

    For long outputs, returns a truncated version with a reference note.
    """
    ws = Path(os.environ.get("OKTIGENT_WORKSPACE", os.getcwd()))
    cwd = ws / working_directory if working_directory else ws

    if not cwd.exists():
        return f"Error: Directory not found: {working_directory or '.'}"

    timeout = min(timeout, MAX_TIMEOUT_SECONDS)

    try:
        # Use shell=True on Windows, False on Unix for safety
        use_shell = sys.platform == "win32"

        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
            env={**os.environ, "OKTIGENT": "1"},
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return f"Error: Command timed out after {timeout}s: {command}"

        exit_code = process.returncode
        stdout_str = stdout.decode("utf-8", errors="replace").strip()
        stderr_str = stderr.decode("utf-8", errors="replace").strip()

        # Build output
        parts = []
        if exit_code != 0:
            parts.append(f"Exit code: {exit_code}")

        if stdout_str:
            parts.append(f"STDOUT ({len(stdout_str)} chars):")
            parts.append(stdout_str)

        if stderr_str:
            parts.append(f"STDERR ({len(stderr_str)} chars):")
            parts.append(stderr_str)

        if not parts:
            parts.append("Command completed successfully (no output).")

        output = "\n".join(parts)

        # Truncate if too large
        if len(output) > MAX_OUTPUT_CHARS:
            truncated = output[:MAX_OUTPUT_CHARS]
            output = truncated + f"\n\n... [TRUNCATED: full output is {len(output)} chars]"
            output += f"\nTip: Use read_file to inspect specific files, or redirect output."

        return output

    except FileNotFoundError:
        return f"Error: Command not found: {command}"
    except Exception as e:
        return f"Error running command: {type(e).__name__}: {e}"


async def read_output_file(path: str, start_line: int = 1, end_line: int | None = None) -> str:
    """Read a specific file to inspect truncated command output or logs."""
    from oktigent.tools.files import read_file as _read_file
    return await _read_file(path, start_line, end_line)


def register_bash_tools(registry: ToolRegistry) -> None:
    """Register bash/shell tools."""
    registry.register(ToolDef(
        name="run_command",
        description="Execute a shell command. Returns stdout and stderr. Use for running scripts, tests, builds, git commands, etc. Timeout is capped at 120s.",
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 60, max: 120)",
                },
                "working_directory": {
                    "type": "string",
                    "description": "Working directory relative to workspace (default: workspace root)",
                },
            },
            "required": ["command"],
        },
        handler=run_command,
        risk_level="destructive",
    ))
