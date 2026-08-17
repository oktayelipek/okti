"""Tool registry — central hub for all tool definitions and dispatch."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Type alias for tool handler functions
ToolHandler = Callable[..., Awaitable[str]]


@dataclass
class ToolDef:
    """Definition of a single tool."""

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=lambda: {
        "type": "object",
        "properties": {},
        "required": [],
    })
    handler: ToolHandler | None = None
    risk_level: str = "low"  # low, medium, high, destructive


class ToolRegistry:
    """Central tool registry — registers tools, produces schemas, dispatches calls."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDef] = {}

    def register(self, tool: ToolDef) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool
        logger.debug("Registered tool: %s (risk=%s)", tool.name, tool.risk_level)

    def get(self, name: str) -> ToolDef | None:
        return self._tools.get(name)

    def list_tools(self) -> list[ToolDef]:
        return list(self._tools.values())

    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def to_schemas(self, format: str = "openai") -> list[dict[str, Any]]:
        """Export all tool definitions as LLM-compatible schemas."""
        schemas = []
        for tool in self._tools.values():
            schemas.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            })
        return schemas

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        """Dispatch a tool call by name. Returns the result string."""
        tool = self._tools.get(name)
        if not tool:
            return f"Error: Unknown tool '{name}'"
        if not tool.handler:
            return f"Error: Tool '{name}' has no handler"

        from okti.telemetry import get_tracer
        with get_tracer().span(
            f"tool.{name}",
            tool=name,
            risk=tool.risk_level,
            arg_count=len(arguments),
        ):
            try:
                result = await tool.handler(**arguments)
                return result
            except Exception as e:
                logger.exception("Tool %s raised an error", name)
                return f"Error executing {name}: {type(e).__name__}: {e}"

    def get_risk_level(self, name: str) -> str:
        tool = self._tools.get(name)
        return tool.risk_level if tool else "high"
