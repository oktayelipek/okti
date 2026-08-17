"""Universal rules engine — auto-detects and unifies rules from Cursor, Cline, Copilot, Aider, and standard formats."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class RuleItem:
    """A single rule or instruction source found in the project."""
    source_type: str  # "cursor", "cline", "copilot", "agents", "claude", "okti"
    path: str
    title: str
    content: str
    globs: list[str] = field(default_factory=list)


def load_universal_rules(workspace: Path | None = None) -> list[RuleItem]:
    """Scan workspace and load instructions from all recognized coding agent formats."""
    ws = workspace or Path(os.environ.get("OKTI_WORKSPACE", Path.cwd()))
    rules: list[RuleItem] = []

    # 1. Cursor: .cursorrules
    cursorrules = ws / ".cursorrules"
    if cursorrules.is_file():
        try:
            content = cursorrules.read_text(encoding="utf-8").strip()
            if content:
                rules.append(RuleItem(
                    source_type="cursor",
                    path=".cursorrules",
                    title="Cursor Rules (.cursorrules)",
                    content=content,
                ))
        except (OSError, UnicodeDecodeError) as e:
            logger.debug("Failed reading .cursorrules: %s", e)

    # 2. Cursor MDC rules: .cursor/rules/*.mdc or .cursor/rules/*.md
    cursor_rules_dir = ws / ".cursor" / "rules"
    if cursor_rules_dir.is_dir():
        for rule_file in sorted(cursor_rules_dir.glob("*.*")):
            if rule_file.suffix in (".mdc", ".md"):
                try:
                    content = rule_file.read_text(encoding="utf-8").strip()
                    if content:
                        rel = str(rule_file.relative_to(ws))
                        rules.append(RuleItem(
                            source_type="cursor_mdc",
                            path=rel,
                            title=f"Cursor Rule ({rule_file.stem})",
                            content=content,
                        ))
                except (OSError, UnicodeDecodeError) as e:
                    logger.debug("Failed reading cursor rule %s: %s", rule_file, e)

    # 3. Cline / RooCode: .clinerules
    clinerules = ws / ".clinerules"
    if clinerules.is_file():
        try:
            content = clinerules.read_text(encoding="utf-8").strip()
            if content:
                rules.append(RuleItem(
                    source_type="cline",
                    path=".clinerules",
                    title="Cline Rules (.clinerules)",
                    content=content,
                ))
        except (OSError, UnicodeDecodeError) as e:
            logger.debug("Failed reading .clinerules: %s", e)

    # 4. GitHub Copilot: .github/copilot-instructions.md
    copilot = ws / ".github" / "copilot-instructions.md"
    if copilot.is_file():
        try:
            content = copilot.read_text(encoding="utf-8").strip()
            if content:
                rules.append(RuleItem(
                    source_type="copilot",
                    path=".github/copilot-instructions.md",
                    title="GitHub Copilot Instructions",
                    content=content,
                ))
        except (OSError, UnicodeDecodeError) as e:
            logger.debug("Failed reading copilot instructions: %s", e)

    # 5. Standard AGENTS.md, CLAUDE.md, GEMINI.md
    for std_name, s_type in [("AGENTS.md", "agents"), ("CLAUDE.md", "claude"), ("GEMINI.md", "gemini")]:
        std_file = ws / std_name
        if std_file.is_file():
            try:
                content = std_file.read_text(encoding="utf-8").strip()
                if content:
                    rules.append(RuleItem(
                        source_type=s_type,
                        path=std_name,
                        title=f"{std_name} Project Standards",
                        content=content,
                    ))
            except (OSError, UnicodeDecodeError) as e:
                logger.debug("Failed reading %s: %s", std_name, e)

    # 6. Okti memory & local rules: .okti/rules/*.md, .okti/memory.md
    okti_rules_dir = ws / ".okti" / "rules"
    if okti_rules_dir.is_dir():
        for r_file in sorted(okti_rules_dir.glob("*.md")):
            try:
                content = r_file.read_text(encoding="utf-8").strip()
                if content:
                    rel = str(r_file.relative_to(ws))
                    rules.append(RuleItem(
                        source_type="okti",
                        path=rel,
                        title=f"Okti Rule ({r_file.stem})",
                        content=content,
                    ))
            except (OSError, UnicodeDecodeError) as e:
                logger.debug("Failed reading okti rule %s: %s", r_file, e)

    okti_mem = ws / ".okti" / "memory.md"
    if okti_mem.is_file():
        try:
            content = okti_mem.read_text(encoding="utf-8").strip()
            if content:
                rules.append(RuleItem(
                    source_type="okti_memory",
                    path=".okti/memory.md",
                    title="Okti Project Memory",
                    content=content,
                ))
        except (OSError, UnicodeDecodeError) as e:
            logger.debug("Failed reading okti memory: %s", e)

    return rules


def render_rules_markdown(rules: list[RuleItem]) -> str:
    """Render all loaded rules into a unified markdown block."""
    if not rules:
        return "No external rules found in workspace."

    sections = [
        "## 📜 Active Project Rules & Instructions\n",
        f"Found {len(rules)} rule file(s) across Cursor, Cline, Copilot, and standard specs:\n",
    ]

    for rule in rules:
        sections.append(f"### 🔹 {rule.title} (`{rule.path}`)\n```markdown\n{rule.content}\n```\n")

    return "\n".join(sections).strip()
