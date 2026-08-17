"""Cross-session user profile — the agent's long-term memory of you.

Where the existing project memory (``okti/context/memory.py``) captures
per-repo rules, the profile lives at ``~/.config/okti/profile.md`` and
persists across every session, every repo, every machine (if you sync
your dotfiles).

The model can update it directly via two tools:

  * ``remember_this(fact, category)`` — append a bullet under a
    category header. Categories exist mainly to keep the file readable;
    new categories are created on first use.
  * ``forget_this(needle)`` — drop lines whose text contains a
    substring. Case-insensitive.

Load-time behaviour is defensive:
  * missing file  → empty string, no error
  * 100 KB cap    → truncated with a marker so a runaway remember loop
                    can't blow up the system prompt
  * unreadable    → warning logged, empty string returned
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_PROFILE_PATH = Path.home() / ".config" / "okti" / "profile.md"
_MAX_PROFILE_BYTES = 100_000
_DEFAULT_CATEGORY = "General"


def _profile_path() -> Path:
    """Resolvable so tests can override the location by env var."""
    import os
    override = os.environ.get("OKTI_PROFILE_PATH")
    return Path(override) if override else _DEFAULT_PROFILE_PATH


def load_user_profile() -> str:
    """Return the profile text (empty string if missing or unreadable)."""
    path = _profile_path()
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        logger.warning("User profile unreadable at %s: %s", path, e)
        return ""
    if len(text) > _MAX_PROFILE_BYTES:
        text = text[:_MAX_PROFILE_BYTES] + "\n\n_[truncated: profile exceeds 100 KB]_\n"
    return text.strip()


def build_profile_prompt(profile: str) -> str:
    """Wrap the profile in a system-prompt block. Empty in → empty out."""
    if not profile:
        return ""
    return (
        "<user_profile>\n"
        "Long-term facts and preferences the user has shared with you.\n"
        "Prefer these over generic defaults, but ask before overriding an\n"
        "explicit instruction in the current turn.\n\n"
        f"{profile}\n"
        "</user_profile>"
    )


# ---------------------------------------------------------------------------
# Mutating helpers — used by the remember_this / forget_this tools
# ---------------------------------------------------------------------------

def _iso_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _slugify_category(name: str) -> str:
    """Trim + collapse whitespace so headers stay stable."""
    return re.sub(r"\s+", " ", (name or _DEFAULT_CATEGORY).strip()).title()


def append_fact(fact: str, category: str = _DEFAULT_CATEGORY) -> str:
    """Append a bullet under the given category header.

    Creates the file (and any missing directory) on first call. Returns
    the human-readable result the tool will show back to the model.
    """
    fact = (fact or "").strip()
    if not fact:
        return "Nothing to remember — empty fact."

    cat = _slugify_category(category)
    bullet = f"- ({_iso_now()}) {fact}"

    path = _profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8") if path.is_file() else ""

    header = f"## {cat}"
    lines = text.splitlines()

    if header in lines:
        # Insert bullet at the end of that category's block
        idx = lines.index(header)
        insert_at = len(lines)
        for j in range(idx + 1, len(lines)):
            if lines[j].startswith("## "):
                insert_at = j
                break
        lines.insert(insert_at, bullet)
        new_text = "\n".join(lines).rstrip() + "\n"
    else:
        prefix = text.rstrip() + "\n\n" if text.strip() else ""
        new_text = f"{prefix}{header}\n{bullet}\n"

    path.write_text(new_text, encoding="utf-8")
    return f"Remembered under {cat}: {fact}"


def forget_facts(needle: str) -> str:
    """Delete every bullet whose text contains ``needle`` (case-insensitive)."""
    needle = (needle or "").strip()
    if not needle:
        return "forget_this needs a non-empty needle."

    path = _profile_path()
    if not path.is_file():
        return "Nothing to forget — profile is empty."

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    kept: list[str] = []
    dropped = 0
    q = needle.lower()
    for line in lines:
        if line.lstrip().startswith("- ") and q in line.lower():
            dropped += 1
            continue
        kept.append(line)

    # Also collapse any header that is now empty
    cleaned: list[str] = []
    i = 0
    while i < len(kept):
        line = kept[i]
        if line.startswith("## "):
            # Peek: keep the header only if there's a bullet before the next header
            has_content = False
            for j in range(i + 1, len(kept)):
                nxt = kept[j]
                if nxt.startswith("## "):
                    break
                if nxt.lstrip().startswith("- "):
                    has_content = True
                    break
            if not has_content:
                i += 1
                continue
        cleaned.append(line)
        i += 1

    path.write_text("\n".join(cleaned).rstrip() + ("\n" if cleaned else ""),
                    encoding="utf-8")
    return f"Forgot {dropped} entry(ies) matching {needle!r}."


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

async def remember_this(fact: str, category: str = _DEFAULT_CATEGORY) -> str:
    """Persist a fact to the cross-session user profile."""
    import asyncio
    return await asyncio.to_thread(append_fact, fact, category)


async def forget_this(needle: str) -> str:
    """Remove profile entries whose text contains ``needle``."""
    import asyncio
    return await asyncio.to_thread(forget_facts, needle)


def register_profile_tools(registry) -> None:  # noqa: ANN001
    from okti.tools.registry import ToolDef

    registry.register(ToolDef(
        name="remember_this",
        description=(
            "Persist a durable fact about the user into their cross-"
            "session profile (~/.config/okti/profile.md). Use for "
            "preferences, coding style, ongoing project context, or "
            "anything the user asks you to remember. Never store "
            "secrets, tokens, or passwords."
        ),
        parameters={
            "type": "object",
            "properties": {
                "fact": {"type": "string", "description": "The fact to remember"},
                "category": {
                    "type": "string",
                    "description": (
                        "Section header the fact goes under, e.g. "
                        "'Preferences', 'Stack', 'Current Focus'. Defaults "
                        "to 'General'."
                    ),
                },
            },
            "required": ["fact"],
        },
        handler=remember_this,
        risk_level="low",
    ))

    registry.register(ToolDef(
        name="forget_this",
        description=(
            "Remove profile entries whose text contains the given "
            "substring (case-insensitive). Use when the user asks you "
            "to forget or update a stored preference. Empty categories "
            "are cleaned up automatically."
        ),
        parameters={
            "type": "object",
            "properties": {
                "needle": {
                    "type": "string",
                    "description": "Substring to match against stored entries",
                },
            },
            "required": ["needle"],
        },
        handler=forget_this,
        risk_level="low",
    ))
