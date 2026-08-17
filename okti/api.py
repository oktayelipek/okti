"""Public plugin API v1.

A stable surface for third-party plugin authors that hides the internal
`ToolDef` dataclass and derives the JSON parameter schema from the
function signature automatically.

Usage
-----

    from okti import tool, TOOLS   # convenience re-exports

    @tool(
        description="Reverse a string.",
        risk_level="low",
    )
    async def reverse(text: str) -> str:
        return text[::-1]

    @tool(description="Add two numbers.")
    async def add(a: int, b: int = 0) -> str:
        return str(a + b)

At the bottom of the plugin file expose TOOLS so the loader picks the
decorated handlers up:

    TOOLS = list_registered()

The decorator accepts:

  * `description` (required) — one-line summary the model sees.
  * `name` (optional) — override the exposed name (defaults to the
    function name).
  * `risk_level` — "low" | "medium" | "high" | "destructive".
  * `params_override` — hand-authored JSON schema if you want full
    control (skips auto-derivation).

Auto-derivation rules
---------------------
  * `str`  → {"type": "string"}
  * `int`  → {"type": "integer"}
  * `float`→ {"type": "number"}
  * `bool` → {"type": "boolean"}
  * `list` / `list[T]` → {"type": "array"}
  * `dict` / `dict[…]` → {"type": "object"}
  * anything else → {"type": "string"} (safe default)
  * parameters without a default land in "required"
  * short docstring first line becomes the description if none is passed

Backwards compatibility
-----------------------
Existing plugins that build `ToolDef` instances directly continue to
work — this module is purely additive.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any, get_args, get_origin, get_type_hints

from okti.tools.registry import ToolDef

logger = logging.getLogger(__name__)

# Module-level registry used by list_registered() so plugin files can
# expose `TOOLS = list_registered()` without threading state through.
_REGISTERED: list[ToolDef] = []


def _python_type_to_json(annotation: Any) -> dict[str, Any]:
    """Best-effort mapping from a Python type annotation to a JSON schema."""
    if annotation is inspect.Parameter.empty:
        return {"type": "string"}

    origin = get_origin(annotation)
    if origin in (list, tuple, set):
        item_args = get_args(annotation)
        schema: dict[str, Any] = {"type": "array"}
        if item_args:
            schema["items"] = _python_type_to_json(item_args[0])
        return schema
    if origin is dict:
        return {"type": "object"}

    # Union / Optional — pick the first non-None member
    if origin is not None:  # e.g. Union
        for arg in get_args(annotation):
            if arg is type(None):
                continue
            return _python_type_to_json(arg)

    if annotation is str:
        return {"type": "string"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation is list:
        return {"type": "array"}
    if annotation is dict:
        return {"type": "object"}

    return {"type": "string"}


def _derive_schema(func: Callable[..., Any]) -> dict[str, Any]:
    """Build a JSON schema object from a function's signature.

    Uses `get_type_hints` so string annotations from
    `from __future__ import annotations` resolve to real types.
    """
    sig = inspect.signature(func)
    try:
        hints = get_type_hints(func, include_extras=False)
    except (NameError, TypeError):
        # Fallback: use raw annotations if hints can't be resolved
        hints = {}

    properties: dict[str, dict[str, Any]] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        annotation = hints.get(name, param.annotation)
        properties[name] = _python_type_to_json(annotation)
        if param.default is inspect.Parameter.empty:
            required.append(name)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


def _first_docstring_line(func: Callable[..., Any]) -> str:
    doc = inspect.getdoc(func) or ""
    return doc.strip().splitlines()[0] if doc.strip() else ""


def tool(
    description: str | None = None,
    *,
    name: str | None = None,
    risk_level: str = "low",
    params_override: dict[str, Any] | None = None,
) -> Callable[[Callable[..., Awaitable[str]]], Callable[..., Awaitable[str]]]:
    """Decorator that registers a plain async function as an okti tool.

    See module docstring for full usage. The decorated function is
    returned unchanged so plugin authors can still unit-test it directly.
    """

    def wrapper(func: Callable[..., Awaitable[str]]) -> Callable[..., Awaitable[str]]:
        if not inspect.iscoroutinefunction(func):
            raise TypeError(
                f"@okti.tool requires an async def function; "
                f"got {func.__name__} which is not a coroutine."
            )

        tool_name = name or func.__name__
        desc = description or _first_docstring_line(func)
        if not desc:
            raise ValueError(
                f"@okti.tool({tool_name}) needs either a description "
                f"argument or a docstring first line."
            )
        schema = params_override or _derive_schema(func)

        _REGISTERED.append(ToolDef(
            name=tool_name,
            description=desc,
            parameters=schema,
            handler=func,
            risk_level=risk_level,
        ))
        logger.debug("@okti.tool registered %s (risk=%s)", tool_name, risk_level)
        return func

    return wrapper


def list_registered() -> list[ToolDef]:
    """Return every tool declared with @tool since the last clear.

    Plugins conventionally end with:

        TOOLS = list_registered()

    which the loader picks up as with hand-authored ToolDef lists.
    """
    return list(_REGISTERED)


def clear_registered() -> None:
    """Test hook: reset the module-level registry between test cases."""
    _REGISTERED.clear()
