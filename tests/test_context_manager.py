"""Tests for context.compaction and context.manager modules."""

from __future__ import annotations

import pytest

from okti.config import ContextConfig, OktiConfig, PermissionsConfig, ProviderID
from okti.context.compaction import (
    _messages_to_text,
    _simple_summary,
    compact_with_model,
)
from okti.context.manager import BackgroundRef, ContextManager
from okti.models.provider import (
    BaseProvider,
    Message,
    ProviderResponse,
    Role,
    TokenUsage,
    ToolCall,
)

# ---------------------------------------------------------------------------
# Compaction module tests
# ---------------------------------------------------------------------------


class _FakeProvider(BaseProvider):
    provider_id = "fake"

    def __init__(self, response_text: str = "SUMMARY", raise_error: bool = False):
        self.response_text = response_text
        self.raise_error = raise_error
        self.received: list[Message] | None = None

    async def chat(self, messages, tools=None, model=None, max_tokens=None, temperature=None):
        self.received = messages
        if self.raise_error:
            raise RuntimeError("provider down")
        return ProviderResponse(
            message=Message(role=Role.ASSISTANT, content=self.response_text),
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            model="fake",
        )

    async def stream_chat(self, *a, **k):  # pragma: no cover - not used
        if False:
            yield None  # type: ignore[unreachable]

    def list_models(self):
        return ["fake"]


def _sample_msgs() -> list[Message]:
    return [
        Message(role=Role.SYSTEM, content="sys prompt"),
        Message(role=Role.USER, content="hello"),
        Message(role=Role.ASSISTANT, content="hi", tool_calls=[]),
        Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": "a.py"})],
        ),
        Message(role=Role.TOOL, content="file body", tool_call_id="c1"),
    ]


def test_messages_to_text_skips_system_and_formats_roles():
    text = _messages_to_text(_sample_msgs())
    assert "sys prompt" not in text  # system skipped
    assert "USER: hello" in text
    assert "ASSISTANT: hi" in text
    assert "ASSISTANT called tool: read_file(" in text
    assert "TOOL RESULT: file body" in text


def test_messages_to_text_truncates_long_bodies():
    long = "x" * 2000
    msgs = [
        Message(role=Role.ASSISTANT, content=long),
        Message(role=Role.TOOL, content=long, tool_call_id="c"),
    ]
    text = _messages_to_text(msgs)
    # ASSISTANT truncated at 500, TOOL at 200
    assert text.count("x") == 500 + 200


def test_simple_summary_counts_messages_and_lists_last_tools():
    msgs = _sample_msgs()
    out = _simple_summary(msgs)
    assert "1 user messages" in out
    assert "2 assistant responses" in out
    assert "Last user message: hello" in out
    assert "Last tools called: read_file" in out


def test_simple_summary_handles_empty():
    out = _simple_summary([])
    assert "0 user messages" in out


async def test_compact_with_model_uses_provider_response():
    provider = _FakeProvider(response_text="model-generated summary")
    out = await compact_with_model(_sample_msgs(), provider, model="fake")
    assert out == "model-generated summary"
    assert provider.received is not None
    # Should send SYSTEM prompt + USER wrapper
    assert provider.received[0].role == Role.SYSTEM
    assert provider.received[1].role == Role.USER


async def test_compact_with_model_falls_back_on_provider_error():
    provider = _FakeProvider(raise_error=True)
    out = await compact_with_model(_sample_msgs(), provider)
    # Fell back to simple summary
    assert "user messages" in out


# ---------------------------------------------------------------------------
# ContextManager tests
# ---------------------------------------------------------------------------


@pytest.fixture
def cm() -> ContextManager:
    return ContextManager(OktiConfig(
        default_provider=ProviderID.OLLAMA,
        default_model="m",
        providers={},
        permissions=PermissionsConfig(yolo=True),
        context=ContextConfig(max_tokens=1000, compaction_threshold=0.75, background_max_chars=50),
    ))


def test_background_ref_char_count_auto_set():
    ref = BackgroundRef(ref_id="r1", label="L", content="abcde")
    assert ref.char_count == 5


def test_store_and_retrieve_background(cm: ContextManager):
    rid = cm.store_background("output", "some content")
    assert cm.get_background(rid) == "some content"
    assert cm.get_background("unknown") is None


def test_list_and_summary_of_background_refs(cm: ContextManager):
    assert cm.get_background_summary() == ""  # empty case
    r1 = cm.store_background("cmd-out", "aaa")
    r2 = cm.store_background("file-body", "bbbb")
    listed = cm.list_background_refs()
    assert any(r1 in x for x in listed)
    assert any(r2 in x for x in listed)
    summary = cm.get_background_summary()
    assert "Background references available" in summary
    assert r1 in summary and r2 in summary


def test_estimate_tokens_counts_tool_call_metadata(cm: ContextManager):
    msg_plain = Message(role=Role.USER, content="hello world")
    msg_with_tool = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[ToolCall(id="tc_long_id", name="read_file", arguments={"path": "a.py"})],
    )
    a = cm.estimate_tokens([msg_plain])
    b = cm.estimate_tokens([msg_plain, msg_with_tool])
    # b must exceed a — tool call name/id/args all contribute
    assert b > a


def test_estimate_tokens_counts_tool_call_id_on_tool_message(cm: ContextManager):
    tool_msg = Message(role=Role.TOOL, content="result", tool_call_id="tc_abc")
    tool_msg_no_id = Message(role=Role.TOOL, content="result")
    assert cm.estimate_tokens([tool_msg]) > cm.estimate_tokens([tool_msg_no_id])


def test_needs_compaction_thresholding(cm: ContextManager):
    small = [Message(role=Role.USER, content="hi")]
    assert cm.needs_compaction(small) is False
    huge = [Message(role=Role.USER, content="x" * 100_000)]
    assert cm.needs_compaction(huge) is True


def test_truncate_content_shortcircuits_small_input(cm: ContextManager):
    out = cm.truncate_content("small")
    assert out == "small"
    assert cm.background_refs == {}


def test_truncate_content_stores_full_body_in_background(cm: ContextManager):
    long = "a" * 200  # background_max_chars=50 in fixture
    out = cm.truncate_content(long)
    assert "[TRUNCATED: 200 chars total. Ref:" in out
    assert len(cm.background_refs) == 1
    # The full content is retrievable via the stored ref
    stored = next(iter(cm.background_refs.values()))
    assert stored.content == long


def test_truncate_content_respects_explicit_max(cm: ContextManager):
    out = cm.truncate_content("abcdef", max_chars=3)
    assert out.startswith("abc")
    assert "TRUNCATED" in out


async def test_compact_messages_short_conversation_is_unchanged(cm: ContextManager):
    msgs = [
        Message(role=Role.SYSTEM, content="sys"),
        Message(role=Role.USER, content="q1"),
        Message(role=Role.ASSISTANT, content="a1"),
    ]
    result = await cm.compact_messages(msgs)
    assert result == msgs


async def test_compact_messages_empty_stays_empty(cm: ContextManager):
    assert await cm.compact_messages([]) == []


async def test_compact_messages_summarizes_older_with_provider(cm: ContextManager):
    provider = _FakeProvider(response_text="MODEL SUMMARY")
    msgs = [Message(role=Role.SYSTEM, content="sys")] + [
        Message(role=Role.USER if i % 2 == 0 else Role.ASSISTANT, content=f"turn-{i}")
        for i in range(10)
    ]
    result = await cm.compact_messages(msgs, provider=provider)
    # First is system, next is compacted summary, then last 4
    assert result[0].role == Role.SYSTEM
    assert "MODEL SUMMARY" in result[1].content
    assert len(result) == 1 + 1 + 4
    # Background ref was stored for the summary
    assert any(r.label == "compacted-conversation" for r in cm.background_refs.values())


async def test_compact_messages_falls_back_when_provider_errors(cm: ContextManager):
    provider = _FakeProvider(raise_error=True)
    msgs = [Message(role=Role.SYSTEM, content="sys")] + [
        Message(role=Role.USER, content=f"u{i}") for i in range(6)
    ]
    result = await cm.compact_messages(msgs, provider=provider)
    # Summary message injected even though provider failed
    assert "[Context compacted." in result[1].content


async def test_compact_messages_without_provider_uses_simple_summary(cm: ContextManager):
    msgs = [
        Message(role=Role.USER, content=f"u{i}") for i in range(6)
    ]
    result = await cm.compact_messages(msgs)
    assert result[0].role == Role.USER  # summary message uses USER role
    assert "[Context compacted." in result[0].content


def test_manager_simple_summary_covers_all_role_branches(cm: ContextManager):
    msgs = [
        Message(role=Role.USER, content="user says hi"),
        Message(role=Role.ASSISTANT, content="assistant replies"),
        Message(role=Role.ASSISTANT, content="", tool_calls=[
            ToolCall(id="c", name="read_file", arguments={}),
            ToolCall(id="d", name="write_file", arguments={}),
        ]),
        Message(role=Role.TOOL, content="result body", tool_call_id="c"),
    ]
    out = cm._simple_summary(msgs)
    assert "User: user says hi" in out
    assert "Assistant: assistant replies" in out
    assert "Assistant called: read_file, write_file" in out
    assert "Tool result: result body" in out
