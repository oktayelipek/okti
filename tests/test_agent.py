"""Tests for agent loop and streaming."""

import pytest
from oktigent.agent.loop import AgentLoop, StreamEvent
from oktigent.config import OktigentConfig, ProviderID
from oktigent.models.provider import Message, Role, ToolCall, TokenUsage, StreamChunk
from oktigent.tools.registry import ToolRegistry, ToolDef


# ---------------------------------------------------------------------------
# AgentLoop initialization tests
# ---------------------------------------------------------------------------

def test_agent_loop_init():
    config = OktigentConfig()
    loop = AgentLoop(config)
    assert loop.config == config
    assert loop.session_id is None
    assert len(loop.messages) == 0
    assert loop.total_usage.total_tokens == 0


def test_agent_loop_with_custom_registry():
    config = OktigentConfig()
    registry = ToolRegistry()
    registry.register(ToolDef(name="test_tool", description="Test", risk_level="low"))
    loop = AgentLoop(config, registry=registry)
    assert "test_tool" in loop.registry.tool_names()


def test_agent_loop_system_prompt():
    config = OktigentConfig()
    loop = AgentLoop(config)
    assert "oktigent" in loop.system_prompt.lower()
    assert "tool" in loop.system_prompt.lower()


# ---------------------------------------------------------------------------
# StreamEvent tests
# ---------------------------------------------------------------------------

def test_stream_event_creation():
    event = StreamEvent(type="content", content="hello")
    assert event.type == "content"
    assert event.content == "hello"
    assert event.tool == ""
    assert event.arguments == {}


def test_stream_event_tool():
    event = StreamEvent(type="tool_start", tool="read_file", arguments={"path": "test.py"})
    assert event.type == "tool_start"
    assert event.tool == "read_file"
    assert event.arguments == {"path": "test.py"}


def test_stream_event_repr():
    event = StreamEvent(type="content", content="hello world")
    assert "content" in repr(event)
    assert "11" in repr(event)  # len("hello world")


# ---------------------------------------------------------------------------
# Permission level integration
# ---------------------------------------------------------------------------

def test_permission_check_yolo():
    config = OktigentConfig()
    config.permissions.yolo = True
    loop = AgentLoop(config)
    from oktigent.config import PermissionLevel
    assert loop.permissions.check("run_command") == PermissionLevel.ALLOW


def test_permission_check_low_risk():
    config = OktigentConfig()
    loop = AgentLoop(config)
    from oktigent.config import PermissionLevel
    assert loop.permissions.check("read_file") == PermissionLevel.ALLOW


def test_permission_check_destructive():
    config = OktigentConfig()
    loop = AgentLoop(config)
    from oktigent.config import PermissionLevel
    assert loop.permissions.check("run_command") == PermissionLevel.ASK


# ---------------------------------------------------------------------------
# Context manager integration
# ---------------------------------------------------------------------------

def test_context_compaction_trigger():
    config = OktigentConfig()
    config.context.max_tokens = 50  # Very small for testing
    loop = AgentLoop(config)

    # Add many messages to trigger compaction
    for i in range(20):
        loop.messages.append(Message(role=Role.USER, content=f"Message {i} " * 50))
        loop.messages.append(Message(role=Role.ASSISTANT, content=f"Response {i} " * 50))

    assert loop.context.needs_compaction(loop.messages) is True


# ---------------------------------------------------------------------------
# Tool call accumulation
# ---------------------------------------------------------------------------

def test_tool_call_from_raw_openai():
    raw = {
        "id": "call_abc123",
        "type": "function",
        "function": {
            "name": "edit_file",
            "arguments": '{"path": "test.py", "old_string": "x", "new_string": "y"}',
        },
    }
    tc = ToolCall.from_raw(raw)
    assert tc.id == "call_abc123"
    assert tc.name == "edit_file"
    assert tc.arguments["path"] == "test.py"
    assert tc.arguments["old_string"] == "x"


def test_tool_call_from_raw_dict_args():
    raw = {
        "id": "call_def456",
        "type": "function",
        "function": {
            "name": "read_file",
            "arguments": {"path": "test.py", "start_line": 1},
        },
    }
    tc = ToolCall.from_raw(raw)
    assert tc.arguments["path"] == "test.py"
    assert tc.arguments["start_line"] == 1
