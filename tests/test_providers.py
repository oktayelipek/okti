"""Tests for provider implementations with mocks."""

import pytest
from oktigent.models.provider import (
    BaseProvider, Message, ProviderResponse, Role, TokenUsage, ToolCall, StreamChunk,
)
from oktigent.models.factory import create_provider
from oktigent.config import OktigentConfig, ProviderID, ProviderConfig


# ---------------------------------------------------------------------------
# Provider factory tests
# ---------------------------------------------------------------------------

def test_create_provider_ollama():
    config = OktigentConfig(
        default_provider=ProviderID.OLLAMA,
        default_model="codellama",
        providers={"ollama": ProviderConfig(base_url="http://localhost:11434")},
    )
    provider = create_provider(config)
    assert provider is not None
    assert hasattr(provider, 'chat')
    assert hasattr(provider, 'stream_chat')


def test_create_provider_openai():
    config = OktigentConfig(
        default_provider=ProviderID.OPENAI,
        default_model="gpt-4o",
        providers={"openai": ProviderConfig(api_key="test-key")},
    )
    provider = create_provider(config)
    assert provider is not None


def test_create_provider_anthropic():
    config = OktigentConfig(
        default_provider=ProviderID.ANTHROPIC,
        default_model="claude-sonnet-4-20250514",
        providers={"anthropic": ProviderConfig(api_key="test-key")},
    )
    provider = create_provider(config)
    assert provider is not None


def test_create_provider_gemini():
    config = OktigentConfig(
        default_provider=ProviderID.GEMINI,
        default_model="gemini-2.5-flash",
        providers={"gemini": ProviderConfig(api_key="test-key")},
    )
    provider = create_provider(config)
    assert provider is not None


# ---------------------------------------------------------------------------
# Mock provider tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mock_provider_chat(mock_provider):
    messages = [Message(role=Role.USER, content="Hello")]
    response = await mock_provider.chat(messages)
    assert isinstance(response, ProviderResponse)
    assert response.message.content == "Hello from mock!"
    assert response.message.role == Role.ASSISTANT
    assert mock_provider.call_count == 1


@pytest.mark.asyncio
async def test_mock_provider_stream(mock_provider):
    messages = [Message(role=Role.USER, content="Hello")]
    chunks = []
    async for chunk in mock_provider.stream_chat(messages):
        chunks.append(chunk)
    assert len(chunks) >= 1  # At least content + finish
    assert mock_provider.call_count == 1


@pytest.mark.asyncio
async def test_mock_provider_with_tools(mock_provider_with_tools):
    messages = [Message(role=Role.USER, content="Read a file")]
    response = await mock_provider_with_tools.chat(messages)
    assert len(response.message.tool_calls) == 1
    assert response.message.tool_calls[0].name == "read_file"


# ---------------------------------------------------------------------------
# Message tests
# ---------------------------------------------------------------------------

def test_message_none_content_guard():
    """Message.content should never be None."""
    msg = Message(role=Role.ASSISTANT, content=None)
    assert msg.content == ""


def test_message_to_dict_with_content():
    msg = Message(role=Role.ASSISTANT, content="Hello")
    d = msg.to_dict()
    assert d["role"] == "assistant"
    assert d["content"] == "Hello"


def test_message_to_dict_without_content():
    msg = Message(role=Role.ASSISTANT, content="")
    d = msg.to_dict()
    assert "content" not in d


def test_message_to_dict_with_tool_calls():
    tc = ToolCall(id="tc1", name="test_tool", arguments={"key": "val"})
    msg = Message(role=Role.ASSISTANT, content="", tool_calls=[tc])
    d = msg.to_dict()
    assert len(d["tool_calls"]) == 1
    assert d["tool_calls"][0]["function"]["name"] == "test_tool"


# ---------------------------------------------------------------------------
# TokenUsage tests
# ---------------------------------------------------------------------------

def test_token_usage_addition():
    u1 = TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
    u2 = TokenUsage(prompt_tokens=200, completion_tokens=100, total_tokens=300)
    total = u1 + u2
    assert total.prompt_tokens == 300
    assert total.completion_tokens == 150
    assert total.total_tokens == 450


def test_token_usage_cost():
    u = TokenUsage(prompt_tokens=1000, completion_tokens=500, cost_usd=0.05)
    assert u.cost_usd == 0.05


# ---------------------------------------------------------------------------
# ToolCall tests
# ---------------------------------------------------------------------------

def test_tool_call_from_dict():
    tc = ToolCall.from_raw({"id": "123", "function": {"name": "test", "arguments": '{"x": 1}'}})
    assert tc.id == "123"
    assert tc.name == "test"
    assert tc.arguments == {"x": 1}


def test_tool_call_arguments_json():
    tc = ToolCall(id="1", name="test", arguments={"key": "value"})
    json_str = tc.arguments_json()
    assert '"key"' in json_str
    assert '"value"' in json_str


# ---------------------------------------------------------------------------
# Provider config validation
# ---------------------------------------------------------------------------

def test_provider_config_defaults():
    pc = ProviderConfig()
    assert pc.api_key is None
    assert pc.base_url is None
    assert pc.model is None
    assert pc.max_tokens == 8192
    assert pc.temperature == 0.0


def test_provider_config_custom():
    pc = ProviderConfig(api_key="key", model="my-model", max_tokens=4096)
    assert pc.api_key == "key"
    assert pc.model == "my-model"
    assert pc.max_tokens == 4096
