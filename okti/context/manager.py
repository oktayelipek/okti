"""Context manager — manages conversation context, background/foreground split.

Handles large files, command outputs, and references to keep the context
compact while preserving all necessary information.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from okti.config import OktiConfig
from okti.models.provider import Message, Role

logger = logging.getLogger(__name__)


@dataclass
class BackgroundRef:
    """Reference to content stored outside the main context."""

    ref_id: str
    label: str
    content: str
    char_count: int = 0

    def __post_init__(self):
        self.char_count = len(self.content)


class ContextManager:
    """Manages conversation context with background/foreground split."""

    def __init__(self, config: OktiConfig):
        self.config = config
        self.background_refs: dict[str, BackgroundRef] = {}
        self._ref_counter = 0

    def estimate_tokens(self, messages: list[Message]) -> int:
        """Better token estimate using word-boundary heuristic.

        Rules of thumb:
        - English: ~1 token per 4 chars or ~0.75 tokens per word
        - Code: ~1 token per 3 chars (more symbols)
        - CJK/emoji: ~1-2 tokens per character
        - JSON/tool args: ~1 token per 3 chars (braces, quotes)
        """
        total = 0
        for msg in messages:
            total += self._estimate_text_tokens(msg.content)
            for tc in msg.tool_calls:
                total += self._estimate_text_tokens(tc.arguments_json())
                total += self._estimate_text_tokens(tc.name)
                total += self._estimate_text_tokens(tc.id)
            if msg.tool_call_id:
                total += self._estimate_text_tokens(msg.tool_call_id)
        return total

    @staticmethod
    def _estimate_text_tokens(text: str) -> int:
        """Estimate tokens for a text string."""
        if not text:
            return 0
        n = len(text)
        if n == 0:
            return 0
        # CJK characters: roughly 1-2 tokens each
        cjk_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff' or '\u3040' <= c <= '\u30ff' or '\uac00' <= c <= '\ud7af')
        # Words (for English-like text)
        words = len(text.split())
        # Heuristic: max of (chars/4, words*0.75, cjk_count*1.5)
        by_chars = n / 4.0
        by_words = words * 0.75
        by_cjk = cjk_count * 1.5
        return int(max(by_chars, by_words, by_cjk) + 3)  # +3 for message overhead

    def needs_compaction(self, messages: list[Message]) -> bool:
        """Check if context needs compaction."""
        tokens = self.estimate_tokens(messages)
        max_tokens = self.config.context.max_tokens
        threshold = self.config.context.compaction_threshold
        return tokens > max_tokens * threshold

    def store_background(self, label: str, content: str) -> str:
        """Store content in background, return a reference ID."""
        self._ref_counter += 1
        ref_id = f"ref-{self._ref_counter}"
        self.background_refs[ref_id] = BackgroundRef(
            ref_id=ref_id,
            label=label,
            content=content,
        )
        logger.debug("Stored background ref: %s (%d chars)", ref_id, len(content))
        return ref_id

    def get_background(self, ref_id: str) -> str | None:
        ref = self.background_refs.get(ref_id)
        return ref.content if ref else None

    def list_background_refs(self) -> list[str]:
        """List all background references."""
        return [
            f"{ref.ref_id}: {ref.label} ({ref.char_count} chars)"
            for ref in self.background_refs.values()
        ]

    def get_background_summary(self) -> str:
        """Get a summary of all background references for the system prompt."""
        if not self.background_refs:
            return ""
        lines = ["Background references available:"]
        for ref in self.background_refs.values():
            lines.append(f"  - {ref.ref_id}: {ref.label} ({ref.char_count} chars)")
        lines.append("\nTo read a background reference, use read_file on the original path or ask for ref content.")
        return "\n".join(lines)

    async def compact_messages(self, messages: list[Message], provider: Any = None, model: str | None = None) -> list[Message]:
        """Compact messages by summarizing older messages.

        If provider is given, uses model-based compaction for better quality.
        Falls back to simple truncation if provider is not available.
        """
        if not messages:
            return messages

        # Always keep system prompt
        system_msgs = [m for m in messages if m.role == Role.SYSTEM]
        other_msgs = [m for m in messages if m.role != Role.SYSTEM]

        if len(other_msgs) <= 4:
            return messages

        # Keep the last 4 messages intact
        recent = other_msgs[-4:]
        older = other_msgs[:-4]

        # Try model-based compaction if provider available
        if provider is not None:
            try:
                from okti.context.compaction import compact_with_model
                summary_text = await compact_with_model(older, provider, model)
            except Exception:
                # Fallback to simple summary
                summary_text = self._simple_summary(older)
        else:
            summary_text = self._simple_summary(older)

        # Store detailed older messages as background
        ref_id = self.store_background("compacted-conversation", summary_text)

        summary_msg = Message(
            role=Role.USER,
            content=f"[Context compacted. Earlier conversation summarized. Reference: {ref_id}]\n\nSummary of earlier conversation:\n{summary_text}",
        )

        return system_msgs + [summary_msg] + recent

    def _simple_summary(self, messages: list[Message]) -> str:
        """Simple truncation-based summary (fallback)."""
        summary_parts = []
        for msg in messages:
            if msg.role == Role.USER:
                summary_parts.append(f"User: {msg.content[:200]}")
            elif msg.role == Role.ASSISTANT and msg.content:
                summary_parts.append(f"Assistant: {msg.content[:200]}")
            elif msg.role == Role.ASSISTANT and msg.tool_calls:
                tools = ", ".join(tc.name for tc in msg.tool_calls)
                summary_parts.append(f"Assistant called: {tools}")
            elif msg.role == Role.TOOL:
                summary_parts.append(f"Tool result: {msg.content[:100]}")
        return "\n".join(summary_parts)

    def truncate_content(self, content: str, max_chars: int | None = None) -> str:
        """Truncate content and store full version in background if needed."""
        limit = max_chars or self.config.context.background_max_chars

        if len(content) <= limit:
            return content

        # Store full content in background
        ref_id = self.store_background("truncated-output", content)
        truncated = content[:limit]
        truncated += f"\n\n... [TRUNCATED: {len(content)} chars total. Ref: {ref_id}]"
        return truncated
