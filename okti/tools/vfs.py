"""Virtual Filesystem (VFS) URI router — transparently resolves diff://, git://, rule://, skill://, and conflict:// schemes."""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from okti.agent.rules import load_universal_rules, render_rules_markdown

logger = logging.getLogger(__name__)

VFS_SCHEMES = ("diff://", "git://", "rule://", "rules://", "skill://", "skills://", "conflict://")


def is_virtual_uri(path: str) -> bool:
    """Check if the given path is a virtual filesystem URI."""
    if not isinstance(path, str):
        return False
    return any(path.startswith(scheme) for scheme in VFS_SCHEMES)


async def resolve_virtual_uri(uri: str) -> str:
    """Resolve a virtual URI into dynamic markdown content."""
    parsed = urlparse(uri)
    scheme = parsed.scheme.lower()
    host = parsed.netloc.lower()
    path = parsed.path.lstrip("/")
    target = f"{host}/{path}".strip("/") if host else path

    if scheme == "diff":
        return await _resolve_diff_uri(target)
    elif scheme == "git":
        return await _resolve_git_uri(target)
    elif scheme in ("rule", "rules"):
        return _resolve_rule_uri(target)
    elif scheme in ("skill", "skills"):
        return await _resolve_skill_uri(target)
    elif scheme == "conflict":
        return await _resolve_conflict_uri(target)
    else:
        return f"Unknown virtual URI scheme: {scheme}://"


async def _resolve_diff_uri(target: str) -> str:
    """Resolve diff:// schemes (diff://staged, diff://HEAD, diff://unstaged)."""
    target = target.lower()
    cmd = ["git", "diff"]
    if target == "staged" or target == "cached":
        cmd.append("--cached")
    elif target and target != "unstaged":
        cmd.append(target)

    def run_diff():
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            if res.returncode != 0:
                return f"Git diff error: {res.stderr.strip()}"
            out = res.stdout.strip()
            if not out:
                return f"No changes found for diff://{target or 'unstaged'}"
            return f"## Git Diff (`{target or 'unstaged'}`)\n\n```diff\n{out}\n```"
        except Exception as e:
            return f"Failed to execute git diff: {e}"

    return await asyncio.to_thread(run_diff)


async def _resolve_git_uri(target: str) -> str:
    """Resolve git:// schemes (git://status, git://log, git://branch)."""
    target = target.lower()
    if target == "status" or not target:
        cmd = ["git", "status", "--short", "--branch"]
    elif target == "log":
        cmd = ["git", "log", "--oneline", "-n", "15"]
    elif target in ("branch", "branches"):
        cmd = ["git", "branch", "-a"]
    else:
        cmd = ["git", target]

    def run_git():
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            if res.returncode != 0:
                return f"Git error: {res.stderr.strip()}"
            return f"## Git Output (`git {' '.join(cmd[1:])}`)\n\n```\n{res.stdout.strip()}\n```"
        except Exception as e:
            return f"Failed to execute git command: {e}"

    return await asyncio.to_thread(run_git)


def _resolve_rule_uri(target: str) -> str:
    """Resolve rule:// schemes (rule://all, rule://cursor, rule://cline)."""
    rules = load_universal_rules()
    if not rules:
        return "No project rules found."

    target = target.lower()
    if target in ("all", ""):
        return render_rules_markdown(rules)

    # Filter by source type
    filtered = [r for r in rules if target in r.source_type or target in r.path.lower()]
    if not filtered:
        return f"No rules found matching query '{target}'. Available rule files: {', '.join(r.path for r in rules)}"

    return render_rules_markdown(filtered)


async def _resolve_skill_uri(target: str) -> str:
    """Resolve skill:// schemes."""
    if not target:
        return "Usage: `skill://<skill-name>`"

    # Search in .agents/skills/ or global .gemini/config/skills/
    candidates = [
        Path.cwd() / ".agents" / "skills" / target / "SKILL.md",
        Path.home() / ".gemini" / "config" / "skills" / target / "SKILL.md",
    ]

    for cand in candidates:
        if cand.is_file():
            try:
                content = cand.read_text(encoding="utf-8")
                return f"## Skill: {target}\n\n{content}"
            except Exception as e:
                return f"Failed reading skill {target}: {e}"

    return f"Skill '{target}' not found in workspace or global skill registry."


async def _resolve_conflict_uri(target: str) -> str:
    """Resolve conflict:// schemes to detect and inspect merge conflicts."""
    def inspect_conflicts():
        try:
            res = subprocess.run(
                ["git", "diff", "--name-only", "--diff-filter=U"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            unmerged = [f.strip() for f in res.stdout.splitlines() if f.strip()]
            if not unmerged:
                return "No active git merge conflicts found in the repository."

            lines = [f"## ⚔️ Active Merge Conflicts ({len(unmerged)} files)\n"]
            for f in unmerged:
                lines.append(f"- `{f}`")
                p = Path(f)
                if p.is_file():
                    content = p.read_text(encoding="utf-8", errors="replace")
                    # Extract conflict markers
                    conflict_blocks = re.findall(r"<<<<<<<.*?>>>>>>>.*?\n", content, re.DOTALL)
                    if conflict_blocks:
                        lines.append(f"  Found {len(conflict_blocks)} conflict block(s).")

            return "\n".join(lines)
        except Exception as e:
            return f"Failed checking merge conflicts: {e}"

    return await asyncio.to_thread(inspect_conflicts)
