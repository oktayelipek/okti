"""Tests for MCP client and plugin system."""

import pytest
from pathlib import Path
from oktigent.tools.mcp_client import MCPClient, MCPServerConfig, MCPTool, load_mcp_config
from oktigent.tools.plugin import load_plugin, discover_plugins, load_all_plugins, create_plugin_template
from oktigent.tools.registry import ToolRegistry, ToolDef


# ---------------------------------------------------------------------------
# MCP Client tests
# ---------------------------------------------------------------------------

def test_mcp_client_init():
    client = MCPClient()
    assert len(client.list_tools()) == 0


def test_mcp_tool_creation():
    tool = MCPTool(
        name="test_tool",
        description="A test tool",
        parameters={"type": "object", "properties": {"arg": {"type": "string"}}},
        server_name="test_server",
    )
    assert tool.name == "test_tool"
    assert tool.server_name == "test_server"


def test_mcp_server_config():
    config = MCPServerConfig(
        name="test",
        command="echo",
        args=["hello"],
        transport="stdio",
    )
    assert config.name == "test"
    assert config.transport == "stdio"


def test_mcp_tool_schemas():
    client = MCPClient()
    client._tools["test"] = MCPTool(
        name="test",
        description="Test tool",
        parameters={"type": "object", "properties": {}},
        server_name="server1",
    )
    schemas = client.to_tool_schemas()
    assert len(schemas) == 1
    assert schemas[0]["function"]["name"] == "test"
    assert "[MCP:server1]" in schemas[0]["function"]["description"]


def test_load_mcp_config_empty():
    """Test loading MCP config when no file exists."""
    configs = load_mcp_config("/nonexistent/path/mcp.toml")
    assert configs == []


# ---------------------------------------------------------------------------
# Plugin system tests
# ---------------------------------------------------------------------------

def test_plugin_discovery_empty(tmp_path):
    """Test plugin discovery with no plugins."""
    plugins = discover_plugins([tmp_path / "nonexistent"])
    assert plugins == []


def test_plugin_load(tmp_path):
    """Test loading a plugin file."""
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    plugin_file = plugin_dir / "test_plugin.py"
    plugin_file.write_text('''
from oktigent.tools.registry import ToolDef

async def handler(msg: str = "hello") -> str:
    return f"Result: {msg}"

TOOLS = [
    ToolDef(
        name="test_tool",
        description="A test plugin tool",
        parameters={"type": "object", "properties": {"msg": {"type": "string"}}},
        handler=handler,
        risk_level="low",
    ),
]
''')

    tools = load_plugin(plugin_file)
    assert len(tools) == 1
    assert tools[0].name == "test_tool"
    assert tools[0].description == "A test plugin tool"


def test_plugin_no_tools(tmp_path):
    """Test loading a plugin with no TOOLS."""
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    plugin_file = plugin_dir / "empty_plugin.py"
    plugin_file.write_text("# No tools defined\n")

    tools = load_plugin(plugin_file)
    assert len(tools) == 0


def test_load_all_plugins(tmp_path):
    """Test loading all plugins into a registry."""
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    plugin_file = plugin_dir / "my_plugin.py"
    plugin_file.write_text('''
from oktigent.tools.registry import ToolDef

async def handler() -> str:
    return "plugin result"

TOOLS = [
    ToolDef(
        name="my_tool",
        description="My tool",
        handler=handler,
    ),
]
''')

    registry = ToolRegistry()
    count = load_all_plugins(registry, [plugin_dir])
    assert count == 1
    # Tool should be prefixed with plugin name
    tool_names = registry.tool_names()
    assert any("my_tool" in name for name in tool_names)


def test_create_plugin_template(tmp_path):
    """Test creating a plugin template."""
    template_path = create_plugin_template(tmp_path)
    assert template_path.exists()
    assert template_path.name == "example_plugin.py"
    content = template_path.read_text()
    assert "TOOLS" in content
    assert "ToolDef" in content


def test_plugin_broken_syntax(tmp_path):
    """Test loading a plugin with broken syntax."""
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    plugin_file = plugin_dir / "broken.py"
    plugin_file.write_text("def broken(\n")  # Syntax error

    tools = load_plugin(plugin_file)
    assert len(tools) == 0
