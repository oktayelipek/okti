"""File tools — read, write, edit, search, glob, list_dir.

All edit operations are diff-based (token-efficient): the model specifies
exact old_string -> new_string replacements, not entire file rewrites.
"""

from __future__ import annotations

import asyncio
import difflib
import os
import subprocess
from pathlib import Path

from oktigent.tools.registry import ToolDef, ToolRegistry


def _get_workspace() -> Path:
    """Get workspace root from env or CWD."""
    return Path(os.environ.get("OKTIGENT_WORKSPACE", os.getcwd()))


def _resolve_path(path: str) -> Path:
    """Resolve a path relative to workspace, resolve .. and symlinks safely."""
    ws = _get_workspace()
    p = (ws / path).resolve()
    # Safety: ensure the resolved path is within workspace
    try:
        p.relative_to(ws.resolve())
    except ValueError:
        raise ValueError(f"Path escapes workspace: {path}")
    return p


def _read_file_sync(path: str, start_line: int = 1, end_line: int | None = None) -> str:
    try:
        resolved = _resolve_path(path)
    except ValueError as e:
        return f"Error: {e}"
    if not resolved.exists():
        return f"Error: File not found: {path}"
    if resolved.is_dir():
        return f"Error: Path is a directory, not a file: {path}"

    content = resolved.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines(keepends=True)

    total = len(lines)
    if end_line is None:
        end_line = start_line + 500  # default chunk: 500 lines

    start_idx = max(0, start_line - 1)
    end_idx = min(total, end_line)
    chunk = lines[start_idx:end_idx]

    # Add line numbers
    numbered = []
    for i, line in enumerate(chunk, start=start_idx + 1):
        numbered.append(f"{i}: {line.rstrip()}")

    header = f"File: {path} (lines {start_idx + 1}-{end_idx} of {total})"
    return header + "\n" + "\n".join(numbered)


async def read_file(path: str, start_line: int = 1, end_line: int | None = None) -> str:
    """Read file contents with optional line range."""
    return await asyncio.to_thread(_read_file_sync, path, start_line, end_line)


def _write_file_sync(path: str, content: str) -> str:
    try:
        resolved = _resolve_path(path)
    except ValueError as e:
        return f"Error: {e}"
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")
    return f"File written: {path} ({len(content)} chars, {content.count(chr(10)) + 1} lines)"


async def write_file(path: str, content: str) -> str:
    """Write content to a file (create or overwrite)."""
    return await asyncio.to_thread(_write_file_sync, path, content)


def _edit_file_sync(path: str, old_string: str, new_string: str) -> str:
    try:
        resolved = _resolve_path(path)
    except ValueError as e:
        return f"Error: {e}"
    if not resolved.exists():
        return f"Error: File not found: {path}"

    content = resolved.read_text(encoding="utf-8", errors="replace")

    # If exact old_string is missing, try normalized line endings (\r\n -> \n)
    if old_string not in content:
        content_norm = content.replace("\r\n", "\n")
        old_norm = old_string.replace("\r\n", "\n")
        new_norm = new_string.replace("\r\n", "\n")
        if old_norm in content_norm:
            count = content_norm.count(old_norm)
            if count > 1:
                return f"Error: old_string found {count} times in {path}. Provide more context to make it unique."
            new_content = content_norm.replace(old_norm, new_norm, 1)
            resolved.write_text(new_content, encoding="utf-8")
            return f"File edited (normalized line endings): {path}"
        return f"Error: old_string not found in {path}. No changes made."

    count = content.count(old_string)
    if count > 1:
        return f"Error: old_string found {count} times in {path}. Provide more context to make it unique."

    new_content = content.replace(old_string, new_string, 1)
    resolved.write_text(new_content, encoding="utf-8")

    # Generate diff for display
    diff = list(difflib.unified_diff(
        content.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    ))
    diff_text = "".join(diff[:50])  # cap diff output

    lines_added = new_string.count("\n") + 1
    lines_removed = old_string.count("\n") + 1
    return f"File edited: {path} (-{lines_removed} +{lines_added} lines)\n{diff_text}"


async def edit_file(path: str, old_string: str, new_string: str) -> str:
    """Diff-based edit: replace exact old_string with new_string."""
    return await asyncio.to_thread(_edit_file_sync, path, old_string, new_string)


def _multi_edit_sync(path: str, edits: list[dict[str, str]]) -> str:
    try:
        resolved = _resolve_path(path)
    except ValueError as e:
        return f"Error: {e}"
    if not resolved.exists():
        return f"Error: File not found: {path}"

    content = resolved.read_text(encoding="utf-8", errors="replace")
    results = []

    for i, edit in enumerate(edits):
        old = edit.get("old_string", "")
        new = edit.get("new_string", "")
        if old not in content:
            # Fallback with normalized line endings
            content_norm = content.replace("\r\n", "\n")
            old_norm = old.replace("\r\n", "\n")
            new_norm = new.replace("\r\n", "\n")
            if old_norm in content_norm:
                content = content_norm.replace(old_norm, new_norm, 1)
                results.append(f"Edit {i + 1}: applied (normalized)")
                continue
            results.append(f"Edit {i + 1}: old_string not found — skipped")
            continue
        content = content.replace(old, new, 1)
        results.append(f"Edit {i + 1}: applied")

    resolved.write_text(content, encoding="utf-8")
    return f"File: {path} — {len(results)} edits applied\n" + "\n".join(results)


async def multi_edit(path: str, edits: list[dict[str, str]]) -> str:
    """Apply multiple edits to a single file in one tool call."""
    return await asyncio.to_thread(_multi_edit_sync, path, edits)


def _search_files_sync(
    pattern: str,
    path: str = ".",
    include: str | None = None,
    max_results: int = 30,
) -> str:
    ws = _get_workspace()
    target = ws / path

    cmd = ["rg", "--no-heading", "--line-number", "--color=never"]
    if include:
        cmd.extend(["--glob", include])
    cmd.extend(["--max-count", "5", "-l", pattern, str(target)])

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15
        )
        lines = result.stdout.strip().splitlines()
        if not lines:
            return f"No matches found for pattern: {pattern}"
        output = []
        for line in lines[:max_results]:
            output.append(line)
        header = f"Found matches in {len(lines)} files"
        if len(lines) > max_results:
            header += f" (showing {max_results})"
        return header + "\n" + "\n".join(output)
    except FileNotFoundError:
        # Fallback to findstr on Windows
        cmd2 = ["findstr", "/s", "/n", "/i", pattern, str(target / "*")]
        result = subprocess.run(cmd2, capture_output=True, text=True, timeout=15)
        lines = result.stdout.strip().splitlines()[:max_results]
        if not lines:
            return f"No matches found for pattern: {pattern}"
        return f"Results for: {pattern}\n" + "\n".join(lines)


async def search_files(
    pattern: str,
    path: str = ".",
    include: str | None = None,
    max_results: int = 30,
) -> str:
    """Search file contents using ripgrep (rg) or grep fallback."""
    return await asyncio.to_thread(_search_files_sync, pattern, path, include, max_results)


def _glob_files_sync(pattern: str, path: str = ".") -> str:
    ws = _get_workspace()
    target = ws / path
    matches = sorted(target.glob(pattern))

    if not matches:
        return f"No files matched pattern: {pattern}"

    lines = []
    for m in matches[:200]:
        try:
            rel = str(m.relative_to(ws))
        except ValueError:
            rel = str(m)
        if m.is_dir():
            rel += "/"
        lines.append(rel)

    header = f"Found {len(matches)} matches"
    if len(matches) > 200:
        header += " (showing 200)"
    return header + "\n" + "\n".join(lines)


async def glob_files(pattern: str, path: str = ".") -> str:
    """Find files matching a glob pattern."""
    return await asyncio.to_thread(_glob_files_sync, pattern, path)


def _list_dir_sync(path: str = ".") -> str:
    ws = _get_workspace()
    target = ws / path
    if not target.exists():
        return f"Error: Directory not found: {path}"
    if not target.is_dir():
        return f"Error: Not a directory: {path}"

    entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    lines = []
    for entry in entries[:200]:
        name = entry.name
        if entry.is_dir():
            lines.append(f"  {name}/")
        else:
            try:
                size = entry.stat().st_size
                if size < 1024:
                    size_str = f"{size}B"
                elif size < 1024 * 1024:
                    size_str = f"{size / 1024:.1f}KB"
                else:
                    size_str = f"{size / (1024 * 1024):.1f}MB"
            except Exception:
                size_str = "unknown"
            lines.append(f"  {name} ({size_str})")

    return f"Directory: {path}\n" + "\n".join(lines)


async def list_dir(path: str = ".") -> str:
    """List directory contents with type indicators."""
    return await asyncio.to_thread(_list_dir_sync, path)


def register_file_tools(registry: ToolRegistry) -> None:
    """Register all file tools with the registry."""

    registry.register(ToolDef(
        name="read_file",
        description="Read file contents. Returns lines with numbers. Use start_line/end_line to read specific ranges.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to workspace"},
                "start_line": {"type": "integer", "description": "Start line (1-indexed, default: 1)"},
                "end_line": {"type": "integer", "description": "End line (exclusive, default: start+500)"},
            },
            "required": ["path"],
        },
        handler=read_file,
        risk_level="low",
    ))

    registry.register(ToolDef(
        name="write_file",
        description="Write content to a file. Creates parent directories if needed. Overwrites existing files.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to workspace"},
                "content": {"type": "string", "description": "Full file content to write"},
            },
            "required": ["path", "content"],
        },
        handler=write_file,
        risk_level="high",
    ))

    registry.register(ToolDef(
        name="edit_file",
        description="Edit a file by replacing an exact string. This is the primary editing tool — send only the lines to change, not the full file. The old_string must match exactly and uniquely.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to workspace"},
                "old_string": {"type": "string", "description": "Exact text to find and replace"},
                "new_string": {"type": "string", "description": "Replacement text"},
            },
            "required": ["path", "old_string", "new_string"],
        },
        handler=edit_file,
        risk_level="medium",
    ))

    registry.register(ToolDef(
        name="multi_edit",
        description="Apply multiple edits to a single file. Each edit replaces an exact string. More token-efficient than multiple edit_file calls.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to workspace"},
                "edits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "old_string": {"type": "string"},
                            "new_string": {"type": "string"},
                        },
                    },
                    "description": "List of edits to apply sequentially",
                },
            },
            "required": ["path", "edits"],
        },
        handler=multi_edit,
        risk_level="medium",
    ))

    registry.register(ToolDef(
        name="search_files",
        description="Search file contents using regex. Uses ripgrep when available.",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern to search for"},
                "path": {"type": "string", "description": "Directory to search in (default: workspace root)"},
                "include": {"type": "string", "description": "File glob filter (e.g. '*.py')"},
                "max_results": {"type": "integer", "description": "Max results to return (default: 30)"},
            },
            "required": ["pattern"],
        },
        handler=search_files,
        risk_level="low",
    ))

    registry.register(ToolDef(
        name="glob_files",
        description="Find files matching a glob pattern (e.g. '**/*.py', 'src/**/*.ts').",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern"},
                "path": {"type": "string", "description": "Base directory (default: workspace root)"},
            },
            "required": ["pattern"],
        },
        handler=glob_files,
        risk_level="low",
    ))

    registry.register(ToolDef(
        name="list_dir",
        description="List directory contents with file sizes and type indicators.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path (default: workspace root)"},
            },
        },
        handler=list_dir,
        risk_level="low",
    ))
