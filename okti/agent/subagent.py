"""Subagent runner — spawns focused sub-agents for parallel/independent tasks.

Each subagent gets a focused context, limited tools, and bounded turns.
Output can be structured via JSON schema.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from okti.agent.loop import AgentLoop
from okti.models.provider import Message, Role

logger = logging.getLogger(__name__)


@dataclass
class SubagentConfig:
    """Configuration for a subagent run."""

    system_prompt: str
    allowed_tools: list[str] = field(default_factory=lambda: ["read_file", "search_files", "glob_files", "list_dir"])
    max_turns: int = 15
    model: str | None = None
    output_schema: dict[str, Any] | None = None  # JSON schema for structured output


@dataclass
class SubagentResult:
    """Result from a subagent run."""

    output: str
    turn_count: int = 0
    structured_output: dict[str, Any] | None = None
    success: bool = True
    error: str | None = None


class SubagentRunner:
    """Runs subagents with focused context and limited tools."""

    def __init__(self, parent_loop: AgentLoop):
        self.parent_loop = parent_loop

    async def run(
        self,
        prompt: str,
        config: SubagentConfig,
    ) -> SubagentResult:
        """Run a subagent with the given prompt and config."""
        logger.info("Spawning subagent (max_turns=%d, tools=%s)", config.max_turns, config.allowed_tools)

        # Build messages for the subagent
        messages: list[Message] = [
            Message(role=Role.SYSTEM, content=config.system_prompt),
            Message(role=Role.USER, content=prompt),
        ]

        # Create a filtered tool registry (only allowed tools)
        from okti.tools.registry import ToolRegistry
        filtered = ToolRegistry()
        for name in config.allowed_tools:
            tool_def = self.parent_loop.registry.get(name)
            if tool_def:
                filtered.register(tool_def)

        # Create a child agent loop (without full UI integration)
        child_loop = AgentLoop(
            config=self.parent_loop.config,
            registry=filtered,
            system_prompt=config.system_prompt,
        )
        child_loop.provider = self.parent_loop.provider
        child_loop.messages = messages

        # Run the loop
        turn_count = 0
        last_content = ""
        try:
            for turn in range(config.max_turns):
                turn_count = turn + 1
                response = await child_loop._call_model()
                last_content = response.message.content

                if not response.message.tool_calls:
                    break

                await child_loop._execute_tools(response.message.tool_calls)

            # Try to parse structured output
            structured = None
            if config.output_schema:
                try:
                    import json
                    structured = json.loads(last_content)
                except (json.JSONDecodeError, TypeError):
                    structured = None

            return SubagentResult(
                output=last_content,
                turn_count=turn_count,
                structured_output=structured,
                success=True,
            )

        except Exception as e:
            logger.exception("Subagent failed")
            return SubagentResult(
                output=last_content,
                turn_count=turn_count,
                success=False,
                error=str(e),
            )
