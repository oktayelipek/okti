"""Dual-Model Real-Time Advisor — Watches agent turns and injects inline concerns, blockers, and tips."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from oktigent.models.provider import BaseProvider, Message, Role

logger = logging.getLogger(__name__)


@dataclass
class AdvisorNote:
    """An inline advisory note from the second model."""
    level: str  # "blocker", "concern", "tip"
    title: str
    message: str
    fix_hint: str = ""


_ADVISOR_SYSTEM_PROMPT = """You are a fast, sharp real-time Code Advisor watching an autonomous coding agent work.
Inspect the user prompt and the agent's proposed action / response.
Identify any:
- Blocker: catastrophic command, deleting critical files, credentials leak, severe security risk.
- Concern: logic bug, edge case missed, broken type contract, forgotten test.
- Tip: cleaner syntax, standard library alternative, performance boost.

If everything is sound, return an empty array `[]`.
Otherwise, return JSON array only:
```json
[
  {
    "level": "blocker" | "concern" | "tip",
    "title": "Short title",
    "message": "Direct explanation of why this matters",
    "fix_hint": "Concrete recommendation"
  }
]
```
"""


async def run_advisor_check(
    provider: BaseProvider,
    model: str,
    user_prompt: str,
    assistant_content: str,
) -> list[AdvisorNote]:
    """Run lightweight second-model check on the turn output."""
    if not assistant_content.strip():
        return []

    user_input = f"### User Goal:\n{user_prompt[:2000]}\n\n### Agent Output / Action:\n{assistant_content[:5000]}"
    messages = [
        Message(role=Role.SYSTEM, content=_ADVISOR_SYSTEM_PROMPT),
        Message(role=Role.USER, content=user_input),
    ]

    try:
        resp = await provider.chat(
            messages=messages,
            model=model,
            temperature=0.1,
            max_tokens=1000,
        )
        content = resp.message.content
        match = re.search(r"\[.*\]", content, re.DOTALL)
        if not match:
            return []

        raw_list = json.loads(match.group(0))
        return [
            AdvisorNote(
                level=item.get("level", "concern"),
                title=item.get("title", "Notice"),
                message=item.get("message", ""),
                fix_hint=item.get("fix_hint", ""),
            )
            for item in raw_list
            if isinstance(item, dict) and item.get("message")
        ]
    except Exception as e:
        logger.debug("Advisor check skipped: %s", e)
        return []
