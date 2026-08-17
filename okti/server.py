"""HTTP server mode — host an okti AgentLoop for remote clients.

Enables the same core agent from a browser, mobile app, or CI runner.
Ship as an optional extra so the base install stays lean:

    pip install okti[server]
    export OKTI_SERVER_TOKEN=secret
    okti serve --host 0.0.0.0 --port 8765

Endpoints (JSON unless noted)
-----------------------------
    GET  /health                              → {"ok": true}
    POST /v1/sessions                         → {"id": "..."}
    GET  /v1/sessions                         → {"sessions": [...]}
    GET  /v1/sessions/{id}/messages           → {"messages": [...]}
    POST /v1/sessions/{id}/turns              → newline-delimited JSON
        request:  {"prompt": "..."}
        response: chunked stream of {"type": "...", ...}
    DELETE /v1/sessions/{id}                  → {"ok": true}

Auth
----
Every request must present ``Authorization: Bearer <OKTI_SERVER_TOKEN>``
unless the env var is empty (developer mode — logs a big warning).

Not shipped in this cut
-----------------------
* WebSocket streaming (chunked-JSON works everywhere and adds no deps)
* Multi-tenant isolation (each server pinned to one config)
* Fine-grained per-endpoint auth (bearer-only for now)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from aiohttp.web import Application, Request, Response, StreamResponse

    from okti.config import OktiConfig

logger = logging.getLogger(__name__)

ENV_TOKEN = "OKTI_SERVER_TOKEN"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _extract_bearer(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    return auth.split(None, 1)[1].strip() or None


def _auth_middleware(expected_token: str | None):
    """Middleware factory. If token is empty, auth is skipped with a warning."""
    from aiohttp import web

    if not expected_token:
        logger.warning(
            "%s is empty — okti serve is running WITHOUT auth. Bind to "
            "localhost only or set the env var before going public.",
            ENV_TOKEN,
        )

    @web.middleware
    async def middleware(request, handler):
        if request.path == "/health":
            return await handler(request)
        if expected_token:
            supplied = _extract_bearer(request)
            if not supplied or supplied != expected_token:
                return web.json_response(
                    {"error": "unauthorized"}, status=401,
                )
        return await handler(request)

    return middleware


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def _health(_request: Request) -> Response:
    from aiohttp import web
    return web.json_response({"ok": True})


async def _create_session(request: Request) -> Response:
    from aiohttp import web

    from okti.storage.db import Storage

    body: dict[str, Any] = await _read_json(request)
    name = body.get("name")
    workspace = body.get("workspace")
    model = body.get("model")

    storage = Storage()
    await storage.connect()
    try:
        session_id = await storage.create_session(
            name=name, workspace=workspace, model=model,
        )
    finally:
        await storage.close()

    return web.json_response({"id": session_id})


async def _list_sessions(request: Request) -> Response:
    from aiohttp import web

    from okti.storage.db import Storage

    limit = int(request.query.get("limit", "20"))
    storage = Storage()
    await storage.connect()
    try:
        rows = await storage.list_sessions(limit=limit)
    finally:
        await storage.close()
    return web.json_response({"sessions": rows})


async def _get_messages(request: Request) -> Response:
    from aiohttp import web

    from okti.storage.db import Storage

    session_id = request.match_info["id"]
    storage = Storage()
    await storage.connect()
    try:
        messages = await storage.get_messages(session_id)
    finally:
        await storage.close()
    return web.json_response({
        "messages": [
            {
                "role": m.role.value,
                "content": m.content,
                "tool_calls": [
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                    for tc in m.tool_calls
                ],
            } for m in messages
        ],
    })


async def _delete_session(request: Request) -> Response:
    from aiohttp import web

    from okti.storage.db import Storage

    session_id = request.match_info["id"]
    storage = Storage()
    await storage.connect()
    try:
        ok = await storage.delete_session(session_id)
    finally:
        await storage.close()
    return web.json_response({"ok": ok})


async def _turn_stream(request: Request) -> StreamResponse:
    """Run one agent turn and stream events as newline-delimited JSON."""
    from aiohttp import web

    from okti.agent.loop import AgentLoop

    session_id = request.match_info["id"]
    body = await _read_json(request)
    prompt = body.get("prompt", "").strip()
    if not prompt:
        return web.json_response({"error": "prompt required"}, status=400)

    config = request.app["okti_config"]
    agent = AgentLoop(config=config)
    await agent.initialize(session_id=session_id)

    resp = web.StreamResponse(
        status=200,
        headers={"Content-Type": "application/x-ndjson"},
    )
    await resp.prepare(request)

    try:
        async for event in agent.run_streaming(prompt):
            payload: dict[str, Any] = {"type": event.type}
            if event.content:
                payload["content"] = event.content
            if event.tool:
                payload["tool"] = event.tool
            await resp.write((json.dumps(payload) + "\n").encode("utf-8"))
    except asyncio.CancelledError:
        raise
    except Exception as e:  # surface as one last stream event
        logger.exception("Turn stream crashed")
        await resp.write(
            (json.dumps({"type": "error", "content": str(e)}) + "\n").encode("utf-8")
        )

    await resp.write_eof()
    return resp


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def build_app(config: OktiConfig, token: str | None = None) -> Application:
    from aiohttp import web

    token = token if token is not None else os.environ.get(ENV_TOKEN, "")
    app = web.Application(middlewares=[_auth_middleware(token)])
    app["okti_config"] = config

    app.router.add_get("/health", _health)
    app.router.add_post("/v1/sessions", _create_session)
    app.router.add_get("/v1/sessions", _list_sessions)
    app.router.add_get("/v1/sessions/{id}/messages", _get_messages)
    app.router.add_post("/v1/sessions/{id}/turns", _turn_stream)
    app.router.add_delete("/v1/sessions/{id}", _delete_session)
    return app


async def _read_json(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except (ValueError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------

def run(config: OktiConfig, host: str, port: int, token: str | None = None) -> None:
    """Blocking entry point — spins up the aiohttp app."""
    from aiohttp import web

    app = build_app(config, token=token)
    logger.info("okti serve → http://%s:%d", host, port)
    web.run_app(app, host=host, port=port)
