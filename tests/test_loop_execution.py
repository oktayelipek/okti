"""Tests for AgentLoop execution with tools and mock provider."""

from collections.abc import AsyncIterator
from typing import Any

import pytest

from okti.agent.loop import AgentLoop
from okti.config import OktiConfig, PermissionLevel
from okti.models.provider import (
    BaseProvider,
    Message,
    ProviderResponse,
    Role,
    StreamChunk,
    TokenUsage,
    ToolCall,
)
from okti.tools.registry import ToolDef, ToolRegistry


class MockProvider(BaseProvider):
    provider_id = "mock"

    def __init__(self, responses: list[ProviderResponse]):
        self.responses = list(responses)
        self.call_count = 0

    async def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> ProviderResponse:
        if self.call_count < len(self.responses):
            resp = self.responses[self.call_count]
            self.call_count += 1
            return resp
        return ProviderResponse(
            message=Message(role=Role.ASSISTANT, content="Done."),
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
        yield StreamChunk(content_delta="Done.")

    def list_models(self) -> list[str]:
        return ["mock-model"]


@pytest.mark.asyncio
async def test_run_single_direct_response():
    config = OktiConfig()
    config.permissions.yolo = True
    loop = AgentLoop(config)

    mock_resp = ProviderResponse(
        message=Message(role=Role.ASSISTANT, content="Hello, world!"),
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )
    loop.provider = MockProvider([mock_resp])

    result = await loop.run_single("Hi")
    assert result == "Hello, world!"
    assert len(loop.messages) >= 2
    assert loop.messages[-1].content == "Hello, world!"


@pytest.mark.asyncio
async def test_run_single_with_tool_execution():
    config = OktiConfig()
    config.permissions.yolo = True
    registry = ToolRegistry()

    async def sample_tool(text: str = "") -> str:
        return f"Echo: {text}"

    registry.register(ToolDef(
        name="sample_tool",
        description="Sample echo tool",
        handler=sample_tool,
        risk_level="low",
    ))

    loop = AgentLoop(config, registry=registry)

    # First turn: model calls tool
    resp1 = ProviderResponse(
        message=Message(
            role=Role.ASSISTANT,
            content="Let me run sample_tool",
            tool_calls=[ToolCall(id="call_1", name="sample_tool", arguments={"text": "testing"})],
        ),
        usage=TokenUsage(prompt_tokens=15, completion_tokens=10, total_tokens=25),
    )
    # Second turn: model gives final response
    resp2 = ProviderResponse(
        message=Message(role=Role.ASSISTANT, content="Tool returned: Echo: testing"),
        usage=TokenUsage(prompt_tokens=30, completion_tokens=10, total_tokens=40),
    )
    loop.provider = MockProvider([resp1, resp2])

    result = await loop.run_single("Run echo test")
    assert result == "Tool returned: Echo: testing"

    # Verify tool result was recorded in messages
    tool_msgs = [m for m in loop.messages if m.role == Role.TOOL]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].content == "Echo: testing"
    assert tool_msgs[0].tool_call_id == "call_1"


@pytest.mark.asyncio
async def test_execute_tools_permission_deny():
    config = OktiConfig()
    registry = ToolRegistry()

    async def dangerous_tool() -> str:
        return "Executed"

    registry.register(ToolDef(
        name="dangerous_tool",
        description="Dangerous tool",
        handler=dangerous_tool,
        risk_level="destructive",
    ))

    loop = AgentLoop(config, registry=registry)
    loop.permissions.set_session_override("dangerous_tool", PermissionLevel.DENY)

    tool_call = ToolCall(id="call_x", name="dangerous_tool", arguments={})
    results = await loop._execute_tools([tool_call])

    assert "Permission denied" in loop.messages[-1].content


def test_stream_event_result_attribute():
    from okti.agent.loop import StreamEvent

    event = StreamEvent(type="tool_end", tool="read_file", content="file content here")
    assert event.content == "file content here"
    assert event.result == "file content here"

    event2 = StreamEvent(type="tool_end", tool="read_file", result="result passed directly")
    assert event2.content == "result passed directly"
    assert event2.result == "result passed directly"

