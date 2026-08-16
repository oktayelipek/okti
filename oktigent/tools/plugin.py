"""Plugin system — load custom tools from .oktigent/plugins/ or config.

Plugins are Python files that define tools using the oktigent plugin API.
They can be loaded dynamically at startup.

Plugin format:
    from oktigent.tools.registry import ToolDef

    def my_handler(arg1: str, arg2: int = 0) -> str:
        return f"Result: {arg1} {arg2}"

    TOOLS = [
        ToolDef(
            name="my_tool",
            description="My custom tool",
            parameters={...},
            handler=my_handler,
        )
    ]
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any

from oktigent.tools.registry import ToolDef, ToolRegistry

logger = logging.getLogger(__name__)

# Default plugin directories
_PLUGIN_DIRS = [
    Path.home() / ".config" / "oktigent" / "plugins",
    Path.cwd() / ".oktigent" / "plugins",
]


def discover_plugins(extra_dirs: list[Path] | None = None) -> list[Path]:
    """Discover plugin files from known directories."""
    plugin_files = []
    dirs = _PLUGIN_DIRS + (extra_dirs or [])

    for plugin_dir in dirs:
        if not plugin_dir.exists():
            continue
        for py_file in plugin_dir.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            plugin_files.append(py_file)
            logger.debug("Discovered plugin: %s", py_file)

    return plugin_files


def load_plugin(plugin_path: Path) -> list[ToolDef]:
    """Load a single plugin file and return its tools."""
    try:
        spec = importlib.util.spec_from_file_location(
            f"oktigent_plugin_{plugin_path.stem}",
            str(plugin_path),
        )
        if not spec or not spec.loader:
            logger.error("Failed to load plugin spec: %s", plugin_path)
            return []

        module = importlib.util.module_from_spec(spec)
        sys.modules[module.__name__] = module
        spec.loader.exec_module(module)

        tools = getattr(module, "TOOLS", [])
        if not tools:
            logger.warning("Plugin %s has no TOOLS defined", plugin_path.name)
            return []

        loaded = []
        for tool in tools:
            if isinstance(tool, ToolDef):
                loaded.append(tool)
                logger.info("Loaded tool from plugin: %s", tool.name)
            else:
                logger.warning("Invalid tool in plugin %s: %s", plugin_path.name, tool)

        return loaded

    except Exception as e:
        logger.error("Failed to load plugin %s: %s", plugin_path, e)
        return []


def load_all_plugins(registry: ToolRegistry, extra_dirs: list[Path] | None = None) -> int:
    """Discover and load all plugins into the registry.

    Returns the number of tools loaded.
    """
    plugin_files = discover_plugins(extra_dirs)
    total_loaded = 0

    for plugin_file in plugin_files:
        tools = load_plugin(plugin_file)
        for tool in tools:
            # Prefix with plugin name to avoid conflicts
            tool.name = f"plugin_{plugin_file.stem}_{tool.name}"
            registry.register(tool)
            total_loaded += 1

    if total_loaded > 0:
        logger.info("Loaded %d tools from %d plugins", total_loaded, len(plugin_files))

    return total_loaded


# Plugin template for users
PLUGIN_TEMPLATE = '''"""Custom tool plugin for oktigent.

Place this file in ~/.config/oktigent/plugins/ or .oktigent/plugins/
"""

from oktigent.tools.registry import ToolDef


async def my_tool_handler(name: str = "world") -> str:
    """Your tool handler function."""
    return f"Hello, {name}!"


# Register your tools here
TOOLS = [
    ToolDef(
        name="my_tool",
        description="A custom tool that says hello",
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name to greet",
                },
            },
        },
        handler=my_tool_handler,
        risk_level="low",
    ),
]
'''


def create_plugin_template(directory: Path | None = None) -> Path:
    """Create a plugin template in the specified directory."""
    if directory is None:
        directory = Path.home() / ".config" / "oktigent" / "plugins"
    directory.mkdir(parents=True, exist_ok=True)

    template_path = directory / "example_plugin.py"
    template_path.write_text(PLUGIN_TEMPLATE, encoding="utf-8")
    logger.info("Created plugin template: %s", template_path)
    return template_path
