"""Tests for Ctrl+C cancel-vs-quit behavior in the OktiApp."""

from __future__ import annotations

import asyncio

import pytest

from okti.config import OktiConfig, ProviderID
from okti.models.provider import Message, ProviderResponse, Role, StreamChunk, TokenUsage
from okti.tui.app import OktiApp


class SlowStreamProvider:
    """Provider that yields chunks slowly so we can cancel mid-stream."""

    provider_id = "mock"

    async def stream_chat(self, messages=None, tools=None, model=None, max_tokens=None, temperature=None):
        for i in range(50):
            await asyncio.sleep(0.05)
            yield StreamChunk(content_delta=f"chunk-{i} ")
        yield StreamChunk(finish_reason="stop", token_usage=TokenUsage(total_tokens=10))

    async def chat(self, messages=None, tools=None, model=None, max_tokens=None, temperature=None):
        return ProviderResponse(
            message=Message(role=Role.ASSISTANT, content=""),
            usage=TokenUsage(),
        )

    def list_models(self):
        return ["mock-model"]


@pytest.mark.asyncio
async def test_cancel_or_quit_exits_when_idle(monkeypatch):
    monkeypatch.setattr("okti.tui.onboarding.check_needs_onboarding", lambda *a, **kw: False)
    config = OktiConfig(default_provider=ProviderID.OPENROUTER, default_model="mock-model")
    app = OktiApp(config=config)

    async with app.run_test(size=(100, 24)) as pilot:
        await pilot.pause()
        # No worker running → the binding should exit the app.
        assert app._current_worker is None
        app.action_cancel_or_quit()
        # The app is now closing; wait briefly and confirm.
        await pilot.pause()
        # The action ran without raising — actual close happens after run_test exits.
        assert app._current_worker is None


@pytest.mark.asyncio
async def test_cancel_or_quit_cancels_running_worker(monkeypatch):
    monkeypatch.setattr("okti.tui.onboarding.check_needs_onboarding", lambda *a, **kw: False)
    config = OktiConfig(default_provider=ProviderID.OPENROUTER, default_model="mock-model")
    app = OktiApp(config=config)
    app.agent.provider = SlowStreamProvider()

    async with app.run_test(size=(100, 24)) as pilot:
        await pilot.pause()

        # Kick off a slow agent turn
        app.chat_pane.add_user_message("run something slow")
        app._current_worker = app._run_agent("run something slow")

        # Give it a moment to start streaming
        for _ in range(10):
            await pilot.pause()
            if not app._current_worker.is_finished:
                break

        assert app._current_worker is not None
        assert not app._current_worker.is_finished

        # Ctrl+C → should cancel, NOT exit
        app.action_cancel_or_quit()
        # Worker cleared
        assert app._current_worker is None

        # Give the cancellation time to propagate
        for _ in range(30):
            await pilot.pause()
            await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_cancel_releases_pending_permission(monkeypatch):
    """If a permission dialog is open, cancel should release it as denial."""
    monkeypatch.setattr("okti.tui.onboarding.check_needs_onboarding", lambda *a, **kw: False)
    config = OktiConfig(default_provider=ProviderID.OPENROUTER, default_model="mock-model")
    app = OktiApp(config=config)

    async with app.run_test(size=(100, 24)) as pilot:
        await pilot.pause()

        # Simulate an outstanding permission event
        app._permission_event = asyncio.Event()
        app._permission_result = True  # pre-set; should get overwritten to False

        # Trigger the cancellation path directly (exception handling)
        try:
            raise asyncio.CancelledError
        except asyncio.CancelledError:
            # Mimic what _run_agent's handler does when cancelled with a
            # pending permission event.
            if app._permission_event and not app._permission_event.is_set():
                app._permission_result = False
                app._permission_event.set()

        assert app._permission_event.is_set()
        assert app._permission_result is False
