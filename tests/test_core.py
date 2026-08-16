"""Tests for the agent loop and core components."""

from oktigent.config import OktigentConfig, PermissionLevel, ProviderID
from oktigent.models.provider import Message, Role, ToolCall, TokenUsage
from oktigent.tools.registry import ToolRegistry, ToolDef
from oktigent.agent.permissions import PermissionManager
from oktigent.context.manager import ContextManager


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------

def test_default_config():
    config = OktigentConfig()
    assert config.default_provider == ProviderID.OLLAMA
    assert config.default_model == "codellama"
    assert config.permissions.yolo is False
    assert config.context.max_tokens == 128_000


def test_permission_level_defaults():
    config = OktigentConfig()
    assert config.permissions.get_level("unknown_tool") == PermissionLevel.ASK


def test_yolo_overrides():
    config = OktigentConfig()
    config.permissions.yolo = True
    assert config.permissions.get_level("any_tool") == PermissionLevel.ALLOW


# ---------------------------------------------------------------------------
# Message tests
# ---------------------------------------------------------------------------

def test_message_creation():
    msg = Message(role=Role.USER, content="Hello")
    assert msg.role == Role.USER
    assert msg.content == "Hello"
    assert msg.has_tool_calls() is False


def test_tool_call_from_raw():
    raw = {
        "id": "call_123",
        "type": "function",
        "function": {
            "name": "read_file",
            "arguments": '{"path": "test.py"}',
        },
    }
    tc = ToolCall.from_raw(raw)
    assert tc.id == "call_123"
    assert tc.name == "read_file"
    assert tc.arguments == {"path": "test.py"}


def test_message_to_dict():
    msg = Message(role=Role.ASSISTANT, content="Done", tool_calls=[
        ToolCall(id="c1", name="edit_file", arguments={"path": "a.py", "old_string": "x", "new_string": "y"}),
    ])
    d = msg.to_dict()
    assert d["role"] == "assistant"
    assert d["content"] == "Done"
    assert len(d["tool_calls"]) == 1
    assert d["tool_calls"][0]["function"]["name"] == "edit_file"


# ---------------------------------------------------------------------------
# Tool Registry tests
# ---------------------------------------------------------------------------

def test_tool_registry():
    registry = ToolRegistry()

    async def dummy_handler(path: str = "") -> str:
        return f"read {path}"

    registry.register(ToolDef(
        name="read_file",
        description="Read a file",
        handler=dummy_handler,
        risk_level="low",
    ))

    assert "read_file" in registry.tool_names()
    assert registry.get_risk_level("read_file") == "low"
    assert len(registry.to_schemas()) == 1


# ---------------------------------------------------------------------------
# Permission tests
# ---------------------------------------------------------------------------

def test_permission_manager():
    config = OktigentConfig()
    registry = ToolRegistry()
    registry.register(ToolDef(name="read_file", description="Read", risk_level="low"))
    registry.register(ToolDef(name="run_command", description="Run", risk_level="destructive"))

    pm = PermissionManager(config, registry)
    assert pm.is_allowed("read_file") is True  # low risk = auto allow
    assert pm.is_allowed("run_command") is False  # destructive = ask


# ---------------------------------------------------------------------------
# Context Manager tests
# ---------------------------------------------------------------------------

def test_context_manager():
    config = OktigentConfig()
    cm = ContextManager(config)

    messages = [Message(role=Role.USER, content="x" * 1000)]
    assert cm.estimate_tokens(messages) > 0

    # Store background
    ref_id = cm.store_background("test", "hello world")
    assert cm.get_background(ref_id) == "hello world"
    assert len(cm.list_background_refs()) == 1


def test_context_compaction():
    config = OktigentConfig()
    config.context.max_tokens = 100  # tiny for testing
    cm = ContextManager(config)

    messages = [
        Message(role=Role.SYSTEM, content="system"),
        Message(role=Role.USER, content="x" * 500),
        Message(role=Role.ASSISTANT, content="y" * 500),
        Message(role=Role.USER, content="z" * 500),
        Message(role=Role.ASSISTANT, content="w" * 500),
    ]

    # Should need compaction
    assert cm.needs_compaction(messages) is True


# ---------------------------------------------------------------------------
# Token Usage tests
# ---------------------------------------------------------------------------

def test_token_usage_addition():
    u1 = TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
    u2 = TokenUsage(prompt_tokens=200, completion_tokens=100, total_tokens=300)
    result = u1 + u2
    assert result.prompt_tokens == 300
    assert result.completion_tokens == 150
    assert result.total_tokens == 450
