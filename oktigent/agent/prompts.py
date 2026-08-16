"""Prompt manager — loads provider-specific system prompts with memory integration."""

from __future__ import annotations

import logging
from pathlib import Path

from oktigent.context.memory import build_memory_prompt, load_project_memory

logger = logging.getLogger(__name__)

# Fallback system prompt if no file is found
_DEFAULT_SYSTEM_PROMPT = """You are oktigent, an elite AI coding agent. You are an expert software engineer working in a terminal environment.

## Core Capabilities
- Read, write, and edit files (prefer diff-based edits with edit_file for token efficiency)
- Search codebases with regex and glob patterns
- Execute shell commands (tests, builds, git, etc.)
- Fetch web content for documentation
- Git operations (status, diff, commit, push, pull, branch)
- MCP external tool integration

## Operating Principles
1. **Plan before acting**: Understand the full scope before making changes
2. **Diff-based edits**: Always use edit_file (not write_file) when modifying existing files. Send only the exact lines to change.
3. **Verify your work**: Run tests or builds after making changes
4. **Be precise**: Use exact file paths and line references
5. **Be concise**: Minimize your output while being complete
6. **Token efficiency**: Keep tool call arguments minimal. Use multi_edit for multiple changes in one file.

## File Operations
- Use read_file with line ranges to inspect code (don't read entire large files)
- Use search_files to find code patterns
- Use edit_file for surgical edits (preferred over write_file)
- Use multi_edit for multiple changes to the same file

## Git Workflow
- Use git_status_detailed to check repo state
- Use git_diff before committing to review changes
- Use git_add + git_commit for atomic commits
- Write clear commit messages

{memory_section}

You have access to tools. When the user asks you to do something, use the appropriate tools to accomplish it. Always explain what you're doing briefly before and after tool calls."""

_PROVIDER_PROMPT_MAP = {
    "anthropic": "claude.md",
    "openai": "openai.md",
    "gemini": "gemini.md",
    "deepseek": "deepseek.md",
    "ollama": "local.md",
    "openrouter": "openai.md",
    "xai": "openai.md",
}


def load_system_prompt(provider_id: str = "ollama", workspace_dir: Path | None = None) -> str:
    """Load the best matching system prompt for a provider with memory injected."""
    memory = load_project_memory(workspace_dir)
    memory_section = build_memory_prompt(memory) if memory else ""

    prompt_filename = _PROVIDER_PROMPT_MAP.get(provider_id.lower(), "local.md")

    # Search paths for prompt files
    search_dirs = [
        Path(__file__).resolve().parent.parent.parent / "prompts",  # repo root / prompts
        Path.home() / ".config" / "oktigent" / "prompts",
    ]
    if workspace_dir:
        search_dirs.insert(0, Path(workspace_dir) / ".oktigent" / "prompts")

    content = None
    for d in search_dirs:
        target = d / prompt_filename
        if target.exists() and target.is_file():
            try:
                content = target.read_text(encoding="utf-8").strip()
                logger.debug("Loaded system prompt from %s", target)
                break
            except Exception as e:
                logger.warning("Failed to read prompt from %s: %s", target, e)

    if not content:
        content = _DEFAULT_SYSTEM_PROMPT

    if "{memory_section}" in content:
        return content.format(memory_section=memory_section)
    elif memory_section:
        return f"{content}\n\n{memory_section}"
    return content
