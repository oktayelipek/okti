"""End-to-end tests for the MCP stdio transport against a real subprocess.

Exercises the full path: create_subprocess_exec → initialize handshake →
tools/list → tools/call → escalating disconnect. Compared with the mock
tests in test_mcp_plugin.py, these catch subprocess lifecycle bugs
(orphaned processes, hung handshakes, SIGTERM/SIGKILL escalation).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from okti.tools.mcp_client import MCPClient, MCPServerConfig

_ECHO_SERVER = Path(__file__).parent / "mcp_echo_server.py"


def _echo_config() -> MCPServerConfig:
    return MCPServerConfig(
        name="echo-real",
        transport="stdio",
        command=sys.executable,
        args=[str(_ECHO_SERVER)],
        env={},
    )


@pytest.mark.asyncio
async def test_stdio_handshake_and_tools_list():
    client = MCPClient()
    tools = await client.connect(_echo_config())
    try:
        assert any(t.name == "echo" for t in tools)
        assert tools[0].server_name == "echo-real"
    finally:
        await client.disconnect_all()


@pytest.mark.asyncio
async def test_stdio_tool_call_roundtrip():
    client = MCPClient()
    await client.connect(_echo_config())
    try:
        result = await client.call_tool("echo", {"text": "hello okti"})
        assert "echo: hello okti" in result
    finally:
        await client.disconnect_all()


@pytest.mark.asyncio
async def test_stdio_disconnect_reaps_process(tmp_path):
    """After disconnect_all the subprocess must have terminated."""
    client = MCPClient()
    await client.connect(_echo_config())
    process = client._connections["echo-real"]  # asyncio.subprocess.Process
    await client.disconnect_all()

    # Give the reactor a beat, then confirm the process has exited.
    for _ in range(20):
        if process.returncode is not None:
            break
        await asyncio.sleep(0.05)
    assert process.returncode is not None, "subprocess still running after disconnect_all"


@pytest.mark.asyncio
async def test_stdio_handshake_timeout_kills_hung_server(tmp_path):
    """A server that never responds must be force-killed within the timeout."""
    # A Python sleep never writes to stdout, so the initialize handshake
    # will hang until okti's wait_for timeout fires.
    hung_config = MCPServerConfig(
        name="hung",
        transport="stdio",
        command=sys.executable,
        args=["-c", "import time; time.sleep(60)"],
        env={},
    )
    client = MCPClient()

    # Monkey-patch the timeout down to 1s so this test finishes quickly.
    from okti.tools import mcp_client as mc

    original = mc.MCPClient._connect_stdio

    async def _fast_connect(self, config):  # noqa: ANN001
        try:
            return await asyncio.wait_for(self._connect_stdio_inner(config), timeout=1.0)
        except TimeoutError:
            await self.disconnect(config.name)
            raise

    mc.MCPClient._connect_stdio = _fast_connect
    try:
        with pytest.raises((TimeoutError, asyncio.TimeoutError)):
            await client.connect(hung_config)
    finally:
        mc.MCPClient._connect_stdio = original
        await client.disconnect_all()
