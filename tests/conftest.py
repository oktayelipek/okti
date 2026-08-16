"""Shared test fixtures for oktigent test suite."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Generator

import pytest

from oktigent.config import OktigentConfig, ProviderID, ProviderConfig, PermissionsConfig, ContextConfig
from oktigent.models.provider import BaseProvider, Message, ProviderResponse, Role, TokenUsage, ToolCall
from oktigent.tools.registry import ToolRegistry, ToolDef


# ---------------------------------------------------------------------------
# Config fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def config() -> OktigentConfig:
    """Minimal test configuration."""
    return OktigentConfig(
        default_provider=ProviderID.OLLAMA,
        default_model="test-model",
        providers={},
        permissions=PermissionsConfig(yolo=True),
        context=ContextConfig(max_tokens=4096, compaction_threshold=0.75),
    )


@pytest.fixture
def config_with_providers() -> OktigentConfig:
    """Config with multiple providers configured."""
    return OktigentConfig(
        default_provider=ProviderID.OPENAI,
        default_model="gpt-4o",
        providers={
            "openai": ProviderConfig(
                api_key="test-openai-key",
                model="gpt-4o",
            ),
            "anthropic": ProviderConfig(
                api_key="test-anthropic-key",
                model="claude-sonnet-4-20250514",
            ),
            "ollama": ProviderConfig(
                base_url="http://localhost:11434",
                model="codellama",
            ),
        },
        permissions=PermissionsConfig(yolo=False),
    )


# ---------------------------------------------------------------------------
# Provider fixtures
# ---------------------------------------------------------------------------

class MockProvider(BaseProvider):
    """Mock provider for testing without real API calls."""

    provider_id = "mock"

    def __init__(self, response_text: str = "Hello!", tool_calls=None):
        self.response_text = response_text
        self._tool_calls = tool_calls or []
        self.call_count = 0
        self.last_messages = None

    async def chat(self, messages, tools=None, model=None, max_tokens=None, temperature=None):
        self.call_count += 1
        self.last_messages = messages
        return ProviderResponse(
            message=Message(
                role=Role.ASSISTANT,
                content=self.response_text,
                tool_calls=self._tool_calls,
                model="mock-model",
            ),
            usage=TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
            model="mock-model",
        )

    async def stream_chat(self, messages, tools=None, model=None, max_tokens=None, temperature=None):
        from oktigent.models.provider import StreamChunk
        self.call_count += 1
        self.last_messages = messages
        yield StreamChunk(content_delta=self.response_text)
        if self._tool_calls:
            for tc in self._tool_calls:
                yield StreamChunk(tool_call_delta=tc)
        yield StreamChunk(finish_reason="stop", token_usage=TokenUsage(
            prompt_tokens=100, completion_tokens=50, total_tokens=150
        ))

    def list_models(self):
        return ["mock-model"]


@pytest.fixture
def mock_provider() -> MockProvider:
    """A mock provider that returns a simple text response."""
    return MockProvider(response_text="Hello from mock!")


@pytest.fixture
def mock_provider_with_tools() -> MockProvider:
    """A mock provider that returns tool calls."""
    tc = ToolCall(id="mock_tc_1", name="read_file", arguments={"path": "test.py"})
    return MockProvider(response_text="", tool_calls=[tc])


# ---------------------------------------------------------------------------
# Registry fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def empty_registry() -> ToolRegistry:
    """An empty tool registry."""
    return ToolRegistry()


@pytest.fixture
def registry_with_tools(empty_registry: ToolRegistry) -> ToolRegistry:
    """A registry with sample tools registered."""

    async def echo_handler(text: str = "echo") -> str:
        return f"Echo: {text}"

    async def add_handler(a: int = 0, b: int = 0) -> str:
        return str(a + b)

    empty_registry.register(ToolDef(
        name="echo",
        description="Echo back the input text.",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
        },
        handler=echo_handler,
        risk_level="low",
    ))

    empty_registry.register(ToolDef(
        name="add",
        description="Add two numbers.",
        parameters={
            "type": "object",
            "properties": {
                "a": {"type": "integer"},
                "b": {"type": "integer"},
            },
        },
        handler=add_handler,
        risk_level="low",
    ))

    return empty_registry


# ---------------------------------------------------------------------------
# Temp workspace fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    """Create a temporary workspace directory with some files."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')\n")
    (tmp_path / "src" / "utils.py").write_text("def helper(): pass\n")
    (tmp_path / "README.md").write_text("# Test Project\n")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')
    return tmp_path


# ---------------------------------------------------------------------------
# Message fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_messages() -> list[Message]:
    """A sample conversation for testing."""
    return [
        Message(role=Role.SYSTEM, content="You are a helpful assistant."),
        Message(role=Role.USER, content="What is 2+2?"),
        Message(role=Role.ASSISTANT, content="2+2 = 4"),
        Message(role=Role.USER, content="Now read a file"),
        Message(role=Role.ASSISTANT, content="", tool_calls=[
            ToolCall(id="tc_1", name="read_file", arguments={"path": "test.py"})
        ]),
        Message(role=Role.TOOL, content="file contents here", tool_call_id="tc_1"),
        Message(role=Role.ASSISTANT, content="The file contains: file contents here"),
    ]
