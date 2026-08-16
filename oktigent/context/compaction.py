"""Compaction — context summarization for token efficiency.

Uses the model itself to summarize long conversations, keeping
critical information while reducing token count.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from oktigent.models.provider import Message, Role

if TYPE_CHECKING:
    from oktigent.models.provider import BaseProvider

logger = logging.getLogger(__name__)

COMPACTION_SYSTEM_PROMPT = """You are a context compaction assistant. Your job is to summarize a conversation while preserving ALL critical information needed to continue the work.

Preserve exactly:
- All file paths mentioned (exact paths)
- All error messages and their causes
- All code changes made (what was added/removed)
- All decisions and their rationale
- All user preferences stated
- The current state of the task (what's done, what's next)

Compress:
- Repetitive back-and-forth
- Verbose explanations (replace with brief summaries)
- Tool call details (just note what tool was called and result)
- Intermediate reasoning steps

Format the summary as a structured document:
## Current State
[What is the current state of the task]

## Completed Work
[Brief list of what has been done]

## Pending Work
[What still needs to be done]

## Key Files
[File paths and their roles]

## Important Context
[Any errors, decisions, or preferences to remember]
"""


async def compact_with_model(
    messages: list[Message],
    provider: BaseProvider,
    model: str | None = None,
) -> str:
    """Use the model to create a compact summary of the conversation.

    Returns the summary text.
    """
    # Build the compaction request
    compaction_messages = [
        Message(role=Role.SYSTEM, content=COMPACTION_SYSTEM_PROMPT),
        Message(
            role=Role.USER,
            content="Summarize this conversation for context continuation:\n\n"
            + _messages_to_text(messages),
        ),
    ]

    try:
        response = await provider.chat(
            messages=compaction_messages,
            model=model,
            max_tokens=2000,
            temperature=0.0,
        )
        return response.message.content
    except Exception:
        logger.exception("Compaction failed")
        # Fallback: simple truncation summary
        return _simple_summary(messages)


def _messages_to_text(messages: list[Message]) -> str:
    """Convert messages to a readable text format for compaction."""
    parts = []
    for msg in messages:
        if msg.role == Role.SYSTEM:
            continue
        if msg.role == Role.USER:
            parts.append(f"USER: {msg.content}")
        elif msg.role == Role.ASSISTANT:
            if msg.content:
                parts.append(f"ASSISTANT: {msg.content[:500]}")
            for tc in msg.tool_calls:
                parts.append(f"ASSISTANT called tool: {tc.name}({tc.arguments_json()[:200]})")
        elif msg.role == Role.TOOL:
            parts.append(f"TOOL RESULT: {msg.content[:200]}")
    return "\n".join(parts)


def _simple_summary(messages: list[Message]) -> str:
    """Fallback simple summary when model compaction fails."""
    user_msgs = [m for m in messages if m.role == Role.USER]
    assistant_msgs = [m for m in messages if m.role == Role.ASSISTANT]

    summary_parts = [
        f"Conversation summary ({len(user_msgs)} user messages, {len(assistant_msgs)} assistant responses)",
    ]

    # Last user message
    if user_msgs:
        summary_parts.append(f"Last user message: {user_msgs[-1].content[:200]}")

    # Last assistant message
    if assistant_msgs:
        last = assistant_msgs[-1]
        if last.content:
            summary_parts.append(f"Last assistant response: {last.content[:200]}")
        if last.tool_calls:
            tools = [tc.name for tc in last.tool_calls]
            summary_parts.append(f"Last tools called: {', '.join(tools)}")

    return "\n".join(summary_parts)
