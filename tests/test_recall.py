"""Tests for cross-session conversation recall."""

from __future__ import annotations

from pathlib import Path

import pytest

from okti.context.recall import recall, recall_conversations
from okti.models.provider import Message, Role
from okti.storage.db import Storage


@pytest.fixture
async def store(tmp_path: Path, monkeypatch):
    """Point every Storage() call at a fresh temp DB for this test."""
    db_path = tmp_path / "recall.db"
    orig_init = Storage.__init__

    def _init(self, db_path_override=None):  # noqa: ANN001
        orig_init(self, db_path=db_path)

    monkeypatch.setattr(Storage, "__init__", _init)

    s = Storage()
    await s.connect()
    yield s
    await s.close()


async def _add_session(store: Storage, name: str, messages: list[tuple[Role, str]]) -> str:
    sid = await store.create_session(name=name, model="mock")
    for role, content in messages:
        await store.add_message(sid, Message(role=role, content=content))
    return sid


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recall_empty_query_returns_nothing(store):
    assert await recall("") == []
    assert await recall("   ") == []


@pytest.mark.asyncio
async def test_recall_no_sessions(store):
    assert await recall("anything") == []


@pytest.mark.asyncio
async def test_recall_only_system_messages_ignored(store):
    await _add_session(store, "sys", [
        (Role.SYSTEM, "you are helpful, obey the user")
    ])
    hits = await recall("helpful")
    assert hits == []


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recall_ranks_matching_message_first(store):
    sid1 = await _add_session(store, "auth work", [
        (Role.USER, "how do we handle refresh tokens?"),
        (Role.ASSISTANT, "we rotate JWT tokens every 15 minutes"),
    ])
    await _add_session(store, "styling", [
        (Role.USER, "tabs or spaces?"),
        (Role.ASSISTANT, "tabs, per project convention"),
    ])

    hits = await recall("refresh tokens jwt")
    assert hits
    assert hits[0].session_id == sid1
    assert "token" in hits[0].content.lower() or "jwt" in hits[0].content.lower()


@pytest.mark.asyncio
async def test_recall_returns_top_k(store):
    for i in range(6):
        await _add_session(store, f"s{i}", [
            (Role.USER, f"payment refund flow attempt {i}"),
        ])
    hits = await recall("payment refund", top_k=3)
    assert len(hits) == 3


@pytest.mark.asyncio
async def test_recall_camelcase_and_snakecase_tokens_match(store):
    await _add_session(store, "camel", [
        (Role.ASSISTANT, "the parseConfig function reads TOML"),
    ])
    hits = await recall("parse config")
    assert hits
    assert "parseConfig" in hits[0].content


@pytest.mark.asyncio
async def test_recall_no_matches_returns_empty(store):
    await _add_session(store, "a", [(Role.USER, "hello world")])
    assert await recall("quantum entanglement") == []


# ---------------------------------------------------------------------------
# Snippet helpers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_snippet_trims_long_content(store):
    long = "auth flow " * 200
    await _add_session(store, "long", [(Role.USER, long)])
    hits = await recall("auth flow")
    assert hits
    snippet = hits[0].snippet(limit=100)
    assert len(snippet) <= 101   # allow trailing ellipsis
    assert snippet.endswith("…")


@pytest.mark.asyncio
async def test_snippet_short_content_unchanged(store):
    await _add_session(store, "short", [(Role.USER, "auth flow")])
    hits = await recall("auth flow")
    assert hits[0].snippet() == "auth flow"


# ---------------------------------------------------------------------------
# Tool wrapper output
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recall_conversations_groups_by_session(store):
    sid1 = await _add_session(store, "session one", [
        (Role.USER, "how do we handle auth?"),
        (Role.ASSISTANT, "JWT with refresh tokens"),
    ])
    sid2 = await _add_session(store, "session two", [
        (Role.ASSISTANT, "revoke the auth token on logout"),
    ])

    out = await recall_conversations("auth token")
    assert sid1 in out
    assert sid2 in out
    assert "session one" in out
    assert "session two" in out
    assert "/load" in out  # hint to open a session for full context


@pytest.mark.asyncio
async def test_recall_conversations_no_match_message(store):
    await _add_session(store, "s", [(Role.USER, "hello")])
    out = await recall_conversations("does-not-appear-anywhere")
    assert "No past conversations matched" in out
