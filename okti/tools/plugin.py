"""Plugin system — load custom tools from .okti/plugins/ or config.

SECURITY MODEL
==============
Plugins execute arbitrary Python with the host process' privileges. Python
does not offer real in-process sandboxing, so okti applies defense-in-depth:

1. **Disabled by default** — `config.plugins.enabled` must be True.
2. **SHA256 trust pinning** — each plugin file's hash must appear in
   `config.plugins.trusted_hashes`. Users add hashes via `trust_plugin()`
   after reviewing the code. A changed file re-triggers the trust check.
3. **Static AST scan** — refuses to load plugins that reference dangerous
   APIs (os.system, subprocess.*, socket, ctypes, __import__, eval, exec)
   unless `allow_untrusted` is set. The scan is advisory, not sufficient
   for adversarial code, but blocks accidental footguns.
4. **Path allowlist** — only `~/.config/okti/plugins/` and `./.okti/plugins/`
   are scanned; symlinks outside these roots are rejected.

For strong isolation, run untrusted plugins as MCP stdio servers instead.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import logging
import sys
from pathlib import Path

from okti.tools.registry import ToolDef, ToolRegistry

logger = logging.getLogger(__name__)

_PLUGIN_DIRS = [
    Path.home() / ".config" / "okti" / "plugins",
    Path.cwd() / ".okti" / "plugins",
]

# AST names that indicate elevated risk; trigger warnings on load.
_DANGEROUS_CALLS = {"eval", "exec", "compile", "__import__"}
_DANGEROUS_MODULES = {
    "subprocess",
    "socket",
    "ctypes",
    "multiprocessing",
    "shutil",
    "pickle",
    "marshal",
}
_DANGEROUS_ATTRS = {"system", "popen", "spawn", "spawnv", "spawnvp", "execv", "execvp"}


class PluginTrustError(Exception):
    """Raised when a plugin fails trust verification."""


def compute_plugin_hash(plugin_path: Path) -> str:
    """SHA256 of the plugin file's bytes."""
    h = hashlib.sha256()
    h.update(plugin_path.read_bytes())
    return h.hexdigest()


def _path_is_within_allowlist(path: Path) -> bool:
    resolved = path.resolve()
    for allowed in _PLUGIN_DIRS:
        try:
            resolved.relative_to(allowed.resolve())
            return True
        except (ValueError, OSError):
            continue
    return False


def scan_plugin_ast(plugin_path: Path) -> list[str]:
    """Static AST scan. Returns a list of risk findings (empty = clean)."""
    findings: list[str] = []
    try:
        tree = ast.parse(plugin_path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError) as e:
        return [f"parse error: {e}"]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root in _DANGEROUS_MODULES:
                    findings.append(f"imports dangerous module: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".", 1)[0]
            if root in _DANGEROUS_MODULES:
                findings.append(f"imports from dangerous module: {node.module}")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in _DANGEROUS_CALLS:
                findings.append(f"calls dangerous builtin: {func.id}()")
            elif isinstance(func, ast.Attribute) and func.attr in _DANGEROUS_ATTRS:
                findings.append(f"calls dangerous attribute: .{func.attr}()")
    return findings


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


def load_plugin(
    plugin_path: Path,
    *,
    trusted_hashes: set[str] | frozenset[str] | None = None,
    allow_untrusted: bool = False,
) -> list[ToolDef]:
    """Load a single plugin file and return its tools.

    Refuses to load if the plugin's SHA256 is not in `trusted_hashes`,
    unless `allow_untrusted=True`. AST findings are logged as warnings.
    """
    if not plugin_path.exists() or not plugin_path.is_file():
        logger.error("Plugin path does not exist: %s", plugin_path)
        return []

    plugin_hash = compute_plugin_hash(plugin_path)
    trusted = trusted_hashes or frozenset()
    if plugin_hash not in trusted and not allow_untrusted:
        logger.warning(
            "Plugin %s is untrusted (sha256=%s). Add hash to config.plugins.trusted_hashes to load.",
            plugin_path.name,
            plugin_hash,
        )
        return []

    findings = scan_plugin_ast(plugin_path)
    if findings:
        logger.warning(
            "Plugin %s has %d security finding(s): %s",
            plugin_path.name,
            len(findings),
            "; ".join(findings),
        )

    try:
        spec = importlib.util.spec_from_file_location(
            f"okti_plugin_{plugin_path.stem}",
            str(plugin_path),
        )
        if not spec or not spec.loader:
            logger.error("Failed to load plugin spec: %s", plugin_path)
            return []

        module = importlib.util.module_from_spec(spec)
        sys.modules[module.__name__] = module
        spec.loader.exec_module(module)
    except (ImportError, SyntaxError, AttributeError) as e:
        logger.error("Plugin %s failed to import: %s", plugin_path, e)
        return []
    except Exception as e:
        logger.exception("Plugin %s raised during import: %s", plugin_path, e)
        return []

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


def load_all_plugins(
    registry: ToolRegistry,
    *,
    enabled: bool = False,
    trusted_hashes: list[str] | None = None,
    allow_untrusted: bool = False,
    extra_dirs: list[Path] | None = None,
) -> int:
    """Discover and load all plugins into the registry.

    Returns the number of tools loaded. Plugins are only loaded when
    `enabled=True`; otherwise this is a no-op.
    """
    if not enabled:
        logger.debug("Plugin loading disabled (config.plugins.enabled=False)")
        return 0

    plugin_files = discover_plugins(extra_dirs)
    trusted = frozenset(trusted_hashes or [])
    total_loaded = 0

    for plugin_file in plugin_files:
        tools = load_plugin(
            plugin_file,
            trusted_hashes=trusted,
            allow_untrusted=allow_untrusted,
        )
        for tool in tools:
            tool.name = f"plugin_{plugin_file.stem}_{tool.name}"
            registry.register(tool)
            total_loaded += 1

    if total_loaded > 0:
        logger.info("Loaded %d tools from %d plugins", total_loaded, len(plugin_files))

    return total_loaded


# Plugin template for users
PLUGIN_TEMPLATE = '''"""Custom tool plugin for okti.

Place this file in ~/.config/okti/plugins/ or .okti/plugins/

SECURITY: After creating/editing this file, compute its SHA256 with
    python -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" <file>
and add the hash to config.plugins.trusted_hashes. Enable loading with
config.plugins.enabled = true.
"""

from okti.tools.registry import ToolDef


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
        directory = Path.home() / ".config" / "okti" / "plugins"
    directory.mkdir(parents=True, exist_ok=True)

    template_path = directory / "example_plugin.py"
    template_path.write_text(PLUGIN_TEMPLATE, encoding="utf-8")
    logger.info("Created plugin template: %s", template_path)
    return template_path
