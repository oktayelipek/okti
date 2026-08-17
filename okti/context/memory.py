"""Memory — project-level rules and preferences (AGENTS.md / .okti/)."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_MEMORY_FILENAMES = [
    "AGENTS.md",
    ".okti/memory.md",
    ".okti/rules.md",
]


def load_project_memory(workspace: Path | None = None) -> str:
    """Load project-level memory/rules from known files."""
    if workspace is None:
        workspace = Path.cwd()

    parts: list[str] = []

    for filename in _MEMORY_FILENAMES:
        filepath = workspace / filename
        if filepath.exists():
            try:
                content = filepath.read_text(encoding="utf-8")
                parts.append(f"## Rules from {filename}\n\n{content.strip()}")
                logger.debug("Loaded memory from %s", filepath)
            except Exception as e:
                logger.warning("Failed to read %s: %s", filepath, e)

    return "\n\n".join(parts) if parts else ""


def build_memory_prompt(memory_content: str) -> str:
    """Build a system prompt section from project memory."""
    if not memory_content:
        return ""
    return f"""<project_rules>
{memory_content}
</project_rules>

You MUST follow these project rules. They take precedence over your default behavior."""
