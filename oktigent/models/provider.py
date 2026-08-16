"""Unified message types and BaseProvider abstract class.

All providers normalize their output into these types. This is the backbone
of the agent loop — every model (Ollama, OpenAI, Claude, Gemini, etc.)
produces the same Message/ToolCall/ToolResult objects.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ToolCall:
    """A tool invocation requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def arguments_json(self) -> str:
        """Serialize arguments to JSON string."""
        return json.dumps(self.arguments, ensure_ascii=False)

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> ToolCall:
        """Parse from raw provider format (OpenAI-style)."""
        func = raw.get("function", {})
        args = func.get("arguments", "{}")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"_raw": args}
        return cls(
            id=raw.get("id", ""),
            name=func.get("name", raw.get("name", "")),
            arguments=args,
        )


@dataclass
class ToolResult:
    """Result of a tool execution."""

    tool_call_id: str
    content: str
    is_error: bool = False

    def to_message(self) -> Message:
        """Convert to a Message for the conversation."""
        return Message(
            role=Role.TOOL,
            content=self.content,
            tool_call_id=self.tool_call_id,
        )


@dataclass
class TokenUsage:
    """Token usage statistics."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            cost_usd=self.cost_usd + other.cost_usd,
        )


@dataclass
class Message:
    """Unified message format for all providers."""

    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None
    token_usage: TokenUsage | None = None
    model: str | None = None

    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict (OpenAI-style format)."""
        d: dict[str, Any] = {"role": self.role.value}
        if self.content:
            d["content"] = self.content
        if self.tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": tc.arguments_json(),
                    },
                }
                for tc in self.tool_calls
            ]
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.name:
            d["name"] = self.name
        return d


@dataclass
class StreamChunk:
    """A single streaming chunk from a provider."""

    content_delta: str = ""
    tool_call_delta: ToolCall | None = None
    finish_reason: str | None = None
    token_usage: TokenUsage | None = None


# ---------------------------------------------------------------------------
# Provider ABC
# ---------------------------------------------------------------------------

@dataclass
class ProviderResponse:
    """Full (non-streaming) response from a provider."""

    message: Message
    usage: TokenUsage = field(default_factory=TokenUsage)
    model: str = ""


class BaseProvider(ABC):
    """Abstract base for all model providers.

    Subclasses must implement:
      - chat()           → non-streaming full response
      - stream_chat()    → async iterator of StreamChunk
      - list_models()    → available models
    """

    provider_id: str = "base"

    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> ProviderResponse:
        """Send a non-streaming chat request."""
        ...

    @abstractmethod
    async def stream_chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream a chat response."""
        ...
        yield  # Make this a generator
        # Subclasses override this completely

    @abstractmethod
    def list_models(self) -> list[str]:
        """Return available model names for this provider."""
        ...

    def tool_schema(self, tool_def: dict[str, Any]) -> dict[str, Any]:
        """Convert an internal tool definition to provider-native schema.

        Default: OpenAI-compatible format. Providers can override.
        """
        return {
            "type": "function",
            "function": {
                "name": tool_def["name"],
                "description": tool_def.get("description", ""),
                "parameters": tool_def.get("parameters", {"type": "object", "properties": {}}),
            },
        }
