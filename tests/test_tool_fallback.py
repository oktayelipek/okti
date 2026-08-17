"""Tests for the tool-use fallback in OpenAI-compatible providers.

Some providers (e.g. OpenRouter free models) return 404 with a "tool use"
message when the model does not support tool calling. The provider must
detect this and retry without tools rather than surfacing the raw error.
"""

from __future__ import annotations

import json
from unittest import mock

import pytest

from okti.models.openai_compat import OpenAICompatProvider
from okti.models.provider import Message, Role


class _FakeResponse:
    """Minimal httpx.Response stand-in for streaming."""

    def __init__(self, status_code: int, body: bytes = b"", lines: list[str] | None = None):
        self.status_code = status_code
        self._body = body
        self._lines = lines or []

    async def aread(self) -> bytes:
        return self._body

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeStream:
    def __init__(self, response: _FakeResponse):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *args):
        return False


class _FakeClient:
    """Fake httpx.AsyncClient that returns responses in order and records payloads."""

    def __init__(self, responses: list[_FakeResponse], record: list[dict]):
        # Reference the shared list directly (no copy) so that sequential
        # clients consume the next queued response.
        self._responses = responses
        self._record = record

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def stream(self, method: str, url: str, json: dict | None = None, headers: dict | None = None):
        self._record.append({"url": url, "payload": json})
        return _FakeStream(self._responses.pop(0))

    async def post(self, *args, **kwargs):
        raise NotImplementedError


def _tool_404_response() -> _FakeResponse:
    err = {"error": {"message": "No endpoints found that support tool use."}}
    return _FakeResponse(status_code=404, body=json.dumps(err).encode())


def _stream_ok_response(text: str) -> _FakeResponse:
    lines = [
        f"data: {json.dumps({'choices': [{'delta': {'content': text}, 'finish_reason': None}]})}\n",
        "data: [DONE]\n",
    ]
    return _FakeResponse(status_code=200, lines=lines)


@pytest.mark.asyncio
async def test_stream_chat_falls_back_when_tools_unsupported():
    """404 'tool use' error should trigger a retry without tools."""
    provider = OpenAICompatProvider(api_key="test-key", provider_name="openrouter")

    responses = [
        _tool_404_response(),       # first call (with tools) -> 404
        _stream_ok_response("Hi!"),  # retry (without tools) -> 200 stream
    ]
    record: list[dict] = []

    chunks = []
    with mock.patch(
        "okti.models.openai_compat.httpx.AsyncClient",
        side_effect=lambda timeout=120: _FakeClient(responses, record),
    ):
        async for chunk in provider.stream_chat(
            messages=[Message(role=Role.USER, content="hello")],
            tools=[{"type": "function", "function": {"name": "read_file", "description": "x", "parameters": {}}}],
            model="poolside/laguna-s-2.1:free",
        ):
            chunks.append(chunk)

    # Two calls: first with tools (404), second without tools (success)
    assert len(record) == 2, f"expected 2 requests, got {len(record)}"
    assert record[0]["payload"]["tools"] is not None
    assert "tools" not in record[1]["payload"] or record[1]["payload"]["tools"] is None

    contents = [c.content_delta for c in chunks if c.content_delta]
    assert "".join(contents) == "Hi!"


@pytest.mark.asyncio
async def test_stream_chat_raises_on_other_errors():
    """A non-tool 404 (e.g. unknown endpoint) must not silently retry without tools."""
    provider = OpenAICompatProvider(api_key="test-key", provider_name="openrouter")

    responses = [
        _FakeResponse(status_code=404, body=b'{"error":{"message":"model not found"}}'),
    ]
    record: list[dict] = []

    with mock.patch(
        "okti.models.openai_compat.httpx.AsyncClient",
        side_effect=lambda timeout=120: _FakeClient(responses, record),
    ):
        chunks = []
        async for chunk in provider.stream_chat(
            messages=[Message(role=Role.USER, content="hello")],
            tools=[{"type": "function", "function": {"name": "read_file", "description": "x", "parameters": {}}}],
            model="bad/model",
        ):
            chunks.append(chunk)

    # Only one call was made; the error is surfaced as a stream error chunk
    assert len(record) == 1
    assert any("[Stream error" in (c.content_delta or "") for c in chunks)
