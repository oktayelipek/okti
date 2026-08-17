"""Tests for MCP client and plugin system."""

from okti.tools.mcp_client import MCPClient, MCPServerConfig, MCPTool, load_mcp_config
from okti.tools.plugin import (
    create_plugin_template,
    discover_plugins,
    load_all_plugins,
    load_plugin,
)
from okti.tools.registry import ToolRegistry

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
from okti.tools.registry import ToolDef

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

    tools = load_plugin(plugin_file, allow_untrusted=True)
    assert len(tools) == 1
    assert tools[0].name == "test_tool"
    assert tools[0].description == "A test plugin tool"


def test_plugin_no_tools(tmp_path):
    """Test loading a plugin with no TOOLS."""
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    plugin_file = plugin_dir / "empty_plugin.py"
    plugin_file.write_text("# No tools defined\n")

    tools = load_plugin(plugin_file, allow_untrusted=True)
    assert len(tools) == 0


def test_load_all_plugins(tmp_path):
    """Test loading all plugins into a registry."""
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    plugin_file = plugin_dir / "my_plugin.py"
    plugin_file.write_text('''
from okti.tools.registry import ToolDef

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
    count = load_all_plugins(
        registry,
        enabled=True,
        allow_untrusted=True,
        extra_dirs=[plugin_dir],
    )
    assert count == 1
    # Tool should be prefixed with plugin name
    tool_names = registry.tool_names()
    assert any("my_tool" in name for name in tool_names)


def test_create_plugin_template(tmp_path):
    """Template ships the v1 public API — @tool decorator, no raw ToolDef."""
    template_path = create_plugin_template(tmp_path)
    assert template_path.exists()
    assert template_path.name == "example_plugin.py"
    content = template_path.read_text()
    assert "TOOLS" in content
    assert "@tool" in content
    assert "list_registered" in content


def test_plugin_broken_syntax(tmp_path):
    """Test loading a plugin with broken syntax."""
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    plugin_file = plugin_dir / "broken.py"
    plugin_file.write_text("def broken(\n")  # Syntax error

    tools = load_plugin(plugin_file, allow_untrusted=True)
    assert len(tools) == 0


# ---------------------------------------------------------------------------
# Plugin security tests
# ---------------------------------------------------------------------------

from okti.tools.plugin import compute_plugin_hash, scan_plugin_ast


def _write_plugin(tmp_path, name, body):
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir(exist_ok=True)
    p = plugin_dir / name
    p.write_text(body)
    return p


def test_plugin_disabled_by_default(tmp_path):
    plugin_file = _write_plugin(tmp_path, "safe.py", '''
from okti.tools.registry import ToolDef
async def h() -> str: return "ok"
TOOLS = [ToolDef(name="t", description="d", handler=h)]
''')
    registry = ToolRegistry()
    # enabled=False → no plugins loaded even with correct hash
    trusted = [compute_plugin_hash(plugin_file)]
    count = load_all_plugins(registry, enabled=False, trusted_hashes=trusted,
                              extra_dirs=[plugin_file.parent])
    assert count == 0


def test_plugin_untrusted_hash_rejected(tmp_path):
    plugin_file = _write_plugin(tmp_path, "untrusted.py", '''
from okti.tools.registry import ToolDef
async def h() -> str: return "ok"
TOOLS = [ToolDef(name="t", description="d", handler=h)]
''')
    registry = ToolRegistry()
    # enabled but no trusted hash → rejected
    count = load_all_plugins(registry, enabled=True, trusted_hashes=[],
                              extra_dirs=[plugin_file.parent])
    assert count == 0


def test_plugin_trusted_hash_loads(tmp_path):
    plugin_file = _write_plugin(tmp_path, "trusted.py", '''
from okti.tools.registry import ToolDef
async def h() -> str: return "ok"
TOOLS = [ToolDef(name="t", description="d", handler=h)]
''')
    registry = ToolRegistry()
    trusted = [compute_plugin_hash(plugin_file)]
    count = load_all_plugins(registry, enabled=True, trusted_hashes=trusted,
                              extra_dirs=[plugin_file.parent])
    assert count == 1


def test_plugin_hash_changes_on_edit(tmp_path):
    plugin_file = _write_plugin(tmp_path, "edit.py", "TOOLS = []\n")
    h1 = compute_plugin_hash(plugin_file)
    plugin_file.write_text("TOOLS = []  # edited\n")
    h2 = compute_plugin_hash(plugin_file)
    assert h1 != h2


def test_scan_flags_subprocess(tmp_path):
    plugin_file = _write_plugin(tmp_path, "risky.py", '''
import subprocess
subprocess.run(["ls"])
TOOLS = []
''')
    findings = scan_plugin_ast(plugin_file)
    assert any("subprocess" in f for f in findings)


def test_scan_flags_eval(tmp_path):
    plugin_file = _write_plugin(tmp_path, "evil.py", '''
eval("1+1")
TOOLS = []
''')
    findings = scan_plugin_ast(plugin_file)
    assert any("eval" in f for f in findings)


def test_scan_flags_os_system(tmp_path):
    plugin_file = _write_plugin(tmp_path, "syscall.py", '''
import os
os.system("echo pwned")
TOOLS = []
''')
    findings = scan_plugin_ast(plugin_file)
    assert any("system" in f for f in findings)


def test_scan_clean_plugin(tmp_path):
    plugin_file = _write_plugin(tmp_path, "clean.py", '''
from okti.tools.registry import ToolDef
async def h(x: str) -> str: return x.upper()
TOOLS = [ToolDef(name="upper", description="d", handler=h)]
''')
    findings = scan_plugin_ast(plugin_file)
    assert findings == []


def test_load_nonexistent_plugin(tmp_path):
    tools = load_plugin(tmp_path / "missing.py", allow_untrusted=True)
    assert tools == []
