"""MCP (Model Context Protocol) client — connects to external tool servers.

Supports:
- stdio transport (spawn a process)
- SSE transport (HTTP Server-Sent Events)
- Tool discovery and invocation
- Dynamic tool registration into the agent's tool registry
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class MCPTool:
    """A tool discovered from an MCP server."""

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    server_name: str = ""


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server."""

    name: str
    command: str | None = None  # For stdio: command to run
    args: list[str] = field(default_factory=list)  # For stdio: command args
    url: str | None = None  # For SSE: server URL
    env: dict[str, str] = field(default_factory=dict)  # Environment variables
    transport: str = "stdio"  # "stdio" or "sse"


class MCPClient:
    """Client for connecting to MCP servers."""

    def __init__(self):
        self._servers: dict[str, MCPServerConfig] = {}
        self._connections: dict[str, asyncio.subprocess.Process | httpx.AsyncClient] = {}
        self._tools: dict[str, MCPTool] = {}  # tool_name -> MCPTool
        self._server_tools: dict[str, list[str]] = {}  # server_name -> [tool_names]
        self._request_id = 0

    async def connect(self, config: MCPServerConfig) -> list[MCPTool]:
        """Connect to an MCP server and discover its tools."""
        self._servers[config.name] = config
        logger.info("Connecting to MCP server: %s (transport=%s)", config.name, config.transport)

        try:
            if config.transport == "stdio":
                tools = await self._connect_stdio(config)
            elif config.transport == "sse":
                tools = await self._connect_sse(config)
            else:
                raise ValueError(f"Unknown transport: {config.transport}")

            self._server_tools[config.name] = [t.name for t in tools]
            for tool in tools:
                tool.server_name = config.name
                self._tools[tool.name] = tool
                logger.info("  Discovered tool: %s", tool.name)

            return tools
        except Exception as e:
            logger.error("Failed to connect to MCP server %s: %s", config.name, e)
            raise

    async def _connect_stdio(self, config: MCPServerConfig) -> list[MCPTool]:
        """Connect to an MCP server via stdio transport.

        The full handshake (spawn + initialize + tools/list) is bounded by
        a 30-second timeout. On timeout the subprocess is force-killed to
        avoid orphaned processes.
        """
        if not config.command:
            raise ValueError("stdio transport requires a command")

        try:
            return await asyncio.wait_for(
                self._connect_stdio_inner(config),
                timeout=30.0,
            )
        except TimeoutError:
            logger.error("MCP stdio handshake timed out for %s; killing process", config.name)
            await self.disconnect(config.name)
            raise

    async def _connect_stdio_inner(self, config: MCPServerConfig) -> list[MCPTool]:
        env = {**__import__("os").environ, **config.env}
        process = await asyncio.create_subprocess_exec(
            config.command, *config.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self._connections[config.name] = process

        # Initialize handshake
        await self._send_stdio(config.name, {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "okti", "version": "0.1.0"},
            },
        })

        response = await self._recv_stdio(config.name)
        if "error" in response:
            raise RuntimeError(f"MCP init error: {response['error']}")

        await self._send_stdio(config.name, {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        })

        return await self._list_tools_stdio(config.name)

    async def _connect_sse(self, config: MCPServerConfig) -> list[MCPTool]:
        """Connect to an MCP server via SSE transport."""
        if not config.url:
            raise ValueError("sse transport requires a URL")

        client = httpx.AsyncClient(timeout=30)
        self._connections[config.name] = client

        # Initialize
        resp = await client.post(
            f"{config.url}/initialize",
            json={
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "clientInfo": {"name": "okti", "version": "0.1.0"},
                },
            },
        )
        resp.raise_for_status()

        # List tools
        resp = await client.post(
            f"{config.url}/tools/list",
            json={
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "tools/list",
            },
        )
        resp.raise_for_status()
        data = resp.json()

        tools = []
        for t in data.get("result", {}).get("tools", []):
            tools.append(MCPTool(
                name=t["name"],
                description=t.get("description", ""),
                parameters=t.get("inputSchema", {}),
            ))
        return tools

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Call a tool on its MCP server."""
        tool = self._tools.get(tool_name)
        if not tool:
            return f"Error: MCP tool '{tool_name}' not found"

        server_name = tool.server_name
        config = self._servers.get(server_name)
        if not config:
            return f"Error: MCP server '{server_name}' not found"

        try:
            if config.transport == "stdio":
                return await self._call_stdio(server_name, tool_name, arguments)
            elif config.transport == "sse":
                return await self._call_sse(server_name, tool_name, arguments)
            else:
                return f"Error: Unknown transport: {config.transport}"
        except Exception as e:
            return f"Error calling MCP tool {tool_name}: {type(e).__name__}: {e}"

    async def _call_stdio(self, server_name: str, tool_name: str, arguments: dict) -> str:
        """Call a tool via stdio transport."""
        await self._send_stdio(server_name, {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        })
        response = await self._recv_stdio(server_name)
        if "error" in response:
            return f"Error: {response['error']}"
        result = response.get("result", {})
        # MCP returns content array
        contents = result.get("content", [])
        if isinstance(contents, list):
            texts = [c.get("text", str(c)) for c in contents if isinstance(c, dict)]
            return "\n".join(texts) if texts else str(result)
        return str(result)

    async def _call_sse(self, server_name: str, tool_name: str, arguments: dict) -> str:
        """Call a tool via SSE transport."""
        client = self._connections.get(server_name)
        if not client:
            return f"Error: SSE client for {server_name} not connected"

        resp = await client.post(
            f"{self._servers[server_name].url}/tools/call",
            json={
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            },
        )
        resp.raise_for_status()
        data = resp.json()
        result = data.get("result", {})
        contents = result.get("content", [])
        if isinstance(contents, list):
            texts = [c.get("text", str(c)) for c in contents if isinstance(c, dict)]
            return "\n".join(texts) if texts else str(result)
        return str(result)

    async def _list_tools_stdio(self, server_name: str) -> list[MCPTool]:
        """List tools from a stdio server."""
        await self._send_stdio(server_name, {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/list",
        })
        response = await self._recv_stdio(server_name)
        if "error" in response:
            raise RuntimeError(f"MCP tools/list error: {response['error']}")

        tools = []
        for t in response.get("result", {}).get("tools", []):
            tools.append(MCPTool(
                name=t["name"],
                description=t.get("description", ""),
                parameters=t.get("inputSchema", {}),
            ))
        return tools

    async def _send_stdio(self, server_name: str, message: dict) -> None:
        """Send a JSON-RPC message via stdio."""
        process = self._connections.get(server_name)
        if not process or not isinstance(process, asyncio.subprocess.Process):
            raise RuntimeError(f"No stdio connection for {server_name}")

        data = json.dumps(message) + "\n"
        process.stdin.write(data.encode())
        await process.stdin.drain()

    async def _recv_stdio(self, server_name: str) -> dict:
        """Receive a JSON-RPC response via stdio."""
        process = self._connections.get(server_name)
        if not process or not isinstance(process, asyncio.subprocess.Process):
            raise RuntimeError(f"No stdio connection for {server_name}")

        try:
            line = await asyncio.wait_for(process.stdout.readline(), timeout=30)
            if not line:
                return {"error": "Connection closed"}
            return json.loads(line.decode())
        except TimeoutError:
            return {"error": "Timeout waiting for response"}

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def list_tools(self) -> list[MCPTool]:
        """List all discovered MCP tools."""
        return list(self._tools.values())

    def get_tool(self, name: str) -> MCPTool | None:
        return self._tools.get(name)

    def get_tools_by_server(self, server_name: str) -> list[MCPTool]:
        tool_names = self._server_tools.get(server_name, [])
        return [self._tools[n] for n in tool_names if n in self._tools]

    async def disconnect(self, server_name: str) -> None:
        """Disconnect from an MCP server, escalating to SIGKILL after 5s."""
        conn = self._connections.pop(server_name, None)
        if conn:
            if isinstance(conn, asyncio.subprocess.Process):
                if conn.returncode is None:
                    conn.terminate()
                    try:
                        await asyncio.wait_for(conn.wait(), timeout=5.0)
                    except TimeoutError:
                        logger.warning(
                            "MCP server %s did not exit within 5s of SIGTERM; sending SIGKILL",
                            server_name,
                        )
                        conn.kill()
                        try:
                            await asyncio.wait_for(conn.wait(), timeout=2.0)
                        except TimeoutError:
                            logger.error(
                                "MCP server %s still alive after SIGKILL; giving up",
                                server_name,
                            )
            elif isinstance(conn, httpx.AsyncClient):
                await conn.aclose()

        # Remove tools from this server
        tool_names = self._server_tools.pop(server_name, [])
        for name in tool_names:
            self._tools.pop(name, None)

        self._servers.pop(server_name, None)
        logger.info("Disconnected from MCP server: %s", server_name)

    async def disconnect_all(self) -> None:
        """Disconnect from all MCP servers."""
        for name in list(self._servers.keys()):
            await self.disconnect(name)

    def to_tool_schemas(self) -> list[dict[str, Any]]:
        """Export MCP tools as LLM-compatible schemas."""
        schemas = []
        for tool in self._tools.values():
            schemas.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": f"[MCP:{tool.server_name}] {tool.description}",
                    "parameters": tool.parameters or {"type": "object", "properties": {}},
                },
            })
        return schemas


def load_mcp_config(path: str | None = None) -> list[MCPServerConfig]:
    """Load MCP server configurations from a config file."""
    import tomllib
    from pathlib import Path

    config_path = Path(path) if path else Path.home() / ".config" / "okti" / "mcp.toml"
    if not config_path.exists():
        return []

    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    servers = []
    for name, server_data in data.get("servers", {}).items():
        servers.append(MCPServerConfig(
            name=name,
            command=server_data.get("command"),
            args=server_data.get("args", []),
            url=server_data.get("url"),
            env=server_data.get("env", {}),
            transport=server_data.get("transport", "stdio"),
        ))
    return servers
