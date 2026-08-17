"""Tests for the HTTP `okti serve` mode.

Exercised via aiohttp's test client so no real port is bound. The
storage layer is redirected to a temp SQLite file for isolation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("aiohttp")

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from okti.config import OktiConfig  # noqa: E402
from okti.server import build_app  # noqa: E402


@pytest.fixture
def _redirect_storage(tmp_path: Path, monkeypatch):
    """Point okti's Storage at a temp DB file for each test."""
    db_path = tmp_path / "server.db"
    from okti.storage import db as db_mod
    orig_init = db_mod.Storage.__init__

    def _init(self, db_path_override=None):  # noqa: ANN001
        orig_init(self, db_path=db_path)

    monkeypatch.setattr(db_mod.Storage, "__init__", _init)
    return db_path


@pytest.fixture
async def client(_redirect_storage):
    app = build_app(OktiConfig(), token="secret-token")
    async with TestClient(TestServer(app)) as c:
        yield c


def _hdr(token: str = "secret-token") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_needs_no_auth(client):
    r = await client.get("/health")
    assert r.status == 200
    assert (await r.json()) == {"ok": True}


@pytest.mark.asyncio
async def test_protected_endpoint_rejects_without_token(client):
    r = await client.get("/v1/sessions")
    assert r.status == 401


@pytest.mark.asyncio
async def test_protected_endpoint_rejects_wrong_token(client):
    r = await client.get("/v1/sessions", headers=_hdr("nope"))
    assert r.status == 401


@pytest.mark.asyncio
async def test_protected_endpoint_accepts_valid_token(client):
    r = await client.get("/v1/sessions", headers=_hdr())
    assert r.status == 200


@pytest.mark.asyncio
async def test_no_token_configured_disables_auth(_redirect_storage):
    app = build_app(OktiConfig(), token="")
    async with TestClient(TestServer(app)) as c:
        r = await c.get("/v1/sessions")
        assert r.status == 200


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_and_list_session(client):
    r = await client.post(
        "/v1/sessions",
        json={"name": "demo", "model": "mock"},
        headers=_hdr(),
    )
    assert r.status == 200
    body = await r.json()
    session_id = body["id"]
    assert session_id  # 12-char hex

    lst = await client.get("/v1/sessions", headers=_hdr())
    payload = await lst.json()
    ids = [s["id"] for s in payload["sessions"]]
    assert session_id in ids


@pytest.mark.asyncio
async def test_get_messages_empty(client):
    r = await client.post("/v1/sessions", json={}, headers=_hdr())
    session_id = (await r.json())["id"]

    r = await client.get(f"/v1/sessions/{session_id}/messages", headers=_hdr())
    assert r.status == 200
    payload = await r.json()
    assert payload == {"messages": []}


@pytest.mark.asyncio
async def test_delete_session(client):
    r = await client.post("/v1/sessions", json={}, headers=_hdr())
    session_id = (await r.json())["id"]

    r = await client.delete(f"/v1/sessions/{session_id}", headers=_hdr())
    assert r.status == 200
    assert (await r.json())["ok"] is True

    # Listing should no longer include it
    lst = await client.get("/v1/sessions", headers=_hdr())
    ids = [s["id"] for s in (await lst.json())["sessions"]]
    assert session_id not in ids


# ---------------------------------------------------------------------------
# Turn stream (ndjson)
# ---------------------------------------------------------------------------

class _FakeProvider:
    provider_id = "mock"

    def __init__(self, text: str = "hello"):
        self.text = text

    async def stream_chat(self, **_kw):
        from okti.models.provider import StreamChunk, TokenUsage
        for chunk in ("hello ", "world"):
            yield StreamChunk(content_delta=chunk)
        yield StreamChunk(
            finish_reason="stop",
            token_usage=TokenUsage(total_tokens=10),
        )

    async def chat(self, **_kw):
        from okti.models.provider import Message, ProviderResponse, Role, TokenUsage
        return ProviderResponse(
            message=Message(role=Role.ASSISTANT, content=self.text),
            usage=TokenUsage(total_tokens=10),
        )

    def list_models(self):
        return ["mock"]


@pytest.mark.asyncio
async def test_turn_stream_returns_ndjson(client, monkeypatch):
    # Patch AgentLoop to use our fake provider
    from okti.agent import loop as loop_mod
    original_init = loop_mod.AgentLoop.__init__

    def _init(self, config, registry=None, system_prompt=None):
        original_init(self, config, registry=registry, system_prompt=system_prompt)
        self.provider = _FakeProvider()

    monkeypatch.setattr(loop_mod.AgentLoop, "__init__", _init)

    # Create a session first
    r = await client.post("/v1/sessions", json={}, headers=_hdr())
    session_id = (await r.json())["id"]

    r = await client.post(
        f"/v1/sessions/{session_id}/turns",
        json={"prompt": "hi"},
        headers=_hdr(),
    )
    assert r.status == 200
    assert r.headers["Content-Type"] == "application/x-ndjson"

    body = await r.text()
    events = [json.loads(line) for line in body.strip().splitlines() if line]
    types = [e["type"] for e in events]
    # Content chunks land as "content"; end-of-turn lands as "turn_end"
    assert "content" in types or "turn_end" in types


@pytest.mark.asyncio
async def test_turn_requires_prompt(client):
    r = await client.post("/v1/sessions", json={}, headers=_hdr())
    session_id = (await r.json())["id"]

    r = await client.post(
        f"/v1/sessions/{session_id}/turns",
        json={},
        headers=_hdr(),
    )
    assert r.status == 400
