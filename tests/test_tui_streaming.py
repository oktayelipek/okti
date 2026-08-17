"""Regression tests for the TUI streaming response rendering.

Verifies that a streamed assistant response is actually rendered and
scrolled into view (bug: content was received but stayed off-screen
because scroll_end() only fired when the empty widget was mounted).
"""

from __future__ import annotations

import asyncio

import pytest

from okti.config import OktiConfig, ProviderID
from okti.models.provider import Message, ProviderResponse, Role, StreamChunk, TokenUsage
from okti.tui.app import OktiApp
from okti.tui.streaming import StreamingMarkdown


class ChunkedStreamProvider:
    """Fake provider that yields many small content deltas (mimics real streaming)."""

    provider_id = "mock"

    def __init__(self, text: str):
        self.text = text

    async def stream_chat(self, messages=None, tools=None, model=None, max_tokens=None, temperature=None):
        for i in range(0, len(self.text), 10):
            yield StreamChunk(content_delta=self.text[i:i + 10])
        yield StreamChunk(finish_reason="stop", token_usage=TokenUsage(
            prompt_tokens=100, completion_tokens=50, total_tokens=150
        ))

    async def chat(self, messages=None, tools=None, model=None, max_tokens=None, temperature=None):
        return ProviderResponse(
            message=Message(role=Role.ASSISTANT, content=self.text),
            usage=TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
        )

    def list_models(self):
        return ["mock-model"]


async def _run_agent_turn(app: OktiApp, text: str) -> None:
    """Submit a message and wait for the agent worker to finish."""
    app.agent.messages = [Message(role=Role.SYSTEM, content="system")]
    app.chat_pane.add_user_message("hi")
    worker = app._run_agent("hi")
    for _ in range(200):
        await app._pilot_pause()
        if worker.is_finished:
            break
    await asyncio.sleep(0.1)
    await app._pilot_pause()


def _screenshot_contains(app: OktiApp, needle: str) -> bool:
    """Return True if `needle` is drawn to the screen (via exported SVG)."""
    svg = app.export_screenshot()
    text = svg.decode("utf-8", errors="replace") if isinstance(svg, bytes) else str(svg)
    # Textual SVG screenshots encode spaces as &#160; (non-breaking space).
    return needle in text or needle.replace(" ", "\u00a0") in text


@pytest.mark.asyncio
async def test_streamed_response_rendered_and_scrolled(monkeypatch):
    """A long streamed response must be rendered and scrolled into view."""
    monkeypatch.setattr("okti.tui.app.check_needs_onboarding", lambda: False, raising=False)
    monkeypatch.setattr("okti.tui.onboarding.check_needs_onboarding", lambda *a, **kw: False)
    config = OktiConfig(
        default_provider=ProviderID.OPENROUTER,
        default_model="mock-model",
    )
    long_text = "Selam! " * 40  # ~280 chars, wraps to several lines

    app = OktiApp(config=config)
    app.agent.provider = ChunkedStreamProvider(long_text)

    async with app.run_test(size=(100, 24)) as pilot:
        # Patch the app so our helper can pause the pilot
        app._pilot_pause = pilot.pause

        await _run_agent_turn(app, "hi")

        # Find the streaming widget and assert it rendered the full content
        widgets = [w for w in app.chat_pane.children if isinstance(w, StreamingMarkdown)]
        assert widgets, "StreamingMarkdown widget was not mounted in the chat pane"
        widget = widgets[-1]
        assert widget._full_content == long_text
        assert widget.is_mounted

        # The response must be actually DRAWN to the screen (regression guard
        # for the _render_content override bug which left content unrendered).
        assert _screenshot_contains(app, "Selam!"), (
            "response text was stored in the widget but not drawn to the screen"
        )

        # The chat pane must be scrolled to the bottom so the response is visible
        cp = app.chat_pane
        assert cp.max_scroll_y > 0, "content should overflow the viewport for this test"
        assert cp.scroll_y == cp.max_scroll_y, (
            f"chat pane not scrolled to bottom: scroll_y={cp.scroll_y}, "
            f"max_scroll_y={cp.max_scroll_y}"
        )


@pytest.mark.asyncio
async def test_short_streamed_response_rendered(monkeypatch):
    """A short streamed response must also be rendered in the chat pane."""
    monkeypatch.setattr("okti.tui.app.check_needs_onboarding", lambda: False, raising=False)
    monkeypatch.setattr("okti.tui.onboarding.check_needs_onboarding", lambda *a, **kw: False)
    config = OktiConfig(
        default_provider=ProviderID.OPENROUTER,
        default_model="mock-model",
    )

    app = OktiApp(config=config)
    app.agent.provider = ChunkedStreamProvider("Hello world")

    async with app.run_test(size=(100, 24)) as pilot:
        app._pilot_pause = pilot.pause
        await _run_agent_turn(app, "hi")

        widgets = [w for w in app.chat_pane.children if isinstance(w, StreamingMarkdown)]
        assert widgets, "StreamingMarkdown widget was not mounted in the chat pane"
        assert widgets[-1]._full_content == "Hello world"
        assert _screenshot_contains(app, "Hello"), (
            "response text was stored in the widget but not drawn to the screen"
        )
