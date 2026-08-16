"""Tests for subagent runner and execution."""

import pytest
from typing import Any, AsyncIterator
from oktigent.agent.loop import AgentLoop
from oktigent.agent.subagent import SubagentConfig, SubagentRunner
from oktigent.config import OktigentConfig
from oktigent.models.provider import (
    BaseProvider,
    Message,
    ProviderResponse,
    Role,
    StreamChunk,
    TokenUsage,
)


class MockSubagentProvider(BaseProvider):
    provider_id = "mock"

    def __init__(self, response_text: str):
        self.response_text = response_text

    async def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> ProviderResponse:
        return ProviderResponse(
            message=Message(role=Role.ASSISTANT, content=self.response_text),
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    async def stream_chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(content_delta=self.response_text)

    def list_models(self) -> list[str]:
        return ["mock-model"]


@pytest.mark.asyncio
async def test_subagent_runner_plain_output():
    config = OktigentConfig()
    config.permissions.yolo = True
    parent_loop = AgentLoop(config)
    parent_loop.provider = MockSubagentProvider("Subagent completed task.")

    runner = SubagentRunner(parent_loop)
    sub_config = SubagentConfig(
        system_prompt="You are a helper subagent",
        allowed_tools=["read_file"],
        max_turns=5,
    )

    result = await runner.run("Inspect the codebase", sub_config)
    assert result.success is True
    assert result.output == "Subagent completed task."
    assert result.turn_count >= 1


@pytest.mark.asyncio
async def test_subagent_runner_structured_output():
    config = OktigentConfig()
    config.permissions.yolo = True
    parent_loop = AgentLoop(config)
    json_output = '{"files_found": 3, "status": "ok"}'
    parent_loop.provider = MockSubagentProvider(json_output)

    runner = SubagentRunner(parent_loop)
    sub_config = SubagentConfig(
        system_prompt="Return JSON",
        allowed_tools=[],
        max_turns=3,
        output_schema={"type": "object"},
    )

    result = await runner.run("Analyze count", sub_config)
    assert result.success is True
    assert result.structured_output == {"files_found": 3, "status": "ok"}
