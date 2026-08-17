"""Tests for the public plugin API (okti.tool decorator, list_registered)."""

from __future__ import annotations

import pytest

from okti import clear_registered, list_registered, tool
from okti.api import _derive_schema, _python_type_to_json


@pytest.fixture(autouse=True)
def _reset_registry():
    clear_registered()
    yield
    clear_registered()


# ---------------------------------------------------------------------------
# Type mapping
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("py_type, expected_schema", [
    (str,   {"type": "string"}),
    (int,   {"type": "integer"}),
    (float, {"type": "number"}),
    (bool,  {"type": "boolean"}),
    (list,  {"type": "array"}),
    (dict,  {"type": "object"}),
])
def test_type_mapping_primitives(py_type, expected_schema):
    assert _python_type_to_json(py_type) == expected_schema


def test_type_mapping_parametrized_list():
    schema = _python_type_to_json(list[str])
    assert schema["type"] == "array"
    assert schema["items"] == {"type": "string"}


def test_type_mapping_optional_picks_non_none():
    schema = _python_type_to_json(str | None)
    assert schema == {"type": "string"}


def test_type_mapping_unknown_defaults_to_string():
    class Weird:
        pass
    assert _python_type_to_json(Weird) == {"type": "string"}


# ---------------------------------------------------------------------------
# Schema derivation
# ---------------------------------------------------------------------------

def test_derive_schema_marks_required_correctly():
    async def f(a: str, b: int = 0) -> str:
        return f"{a}-{b}"
    schema = _derive_schema(f)
    assert schema["type"] == "object"
    assert set(schema["properties"].keys()) == {"a", "b"}
    assert schema["properties"]["a"] == {"type": "string"}
    assert schema["properties"]["b"] == {"type": "integer"}
    assert schema["required"] == ["a"]


def test_derive_schema_skips_self_and_varargs():
    class Holder:
        async def method(self, x: str, *args, **kwargs) -> str:
            return x
    schema = _derive_schema(Holder.method)
    assert list(schema["properties"].keys()) == ["x"]


def test_derive_schema_no_annotation_defaults_to_string():
    async def f(x) -> str:
        return str(x)
    schema = _derive_schema(f)
    assert schema["properties"]["x"] == {"type": "string"}


# ---------------------------------------------------------------------------
# @tool decorator
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_decorator_registers_and_leaves_function_callable():
    @tool(description="Reverse text.", risk_level="low")
    async def reverse(text: str) -> str:
        return text[::-1]

    # The function still works directly
    assert await reverse("hello") == "olleh"

    # And it's in the registry
    tools = list_registered()
    assert len(tools) == 1
    assert tools[0].name == "reverse"
    assert tools[0].description == "Reverse text."
    assert tools[0].risk_level == "low"
    assert tools[0].parameters["required"] == ["text"]


def test_decorator_uses_docstring_when_no_description():
    @tool()
    async def upper(text: str) -> str:
        """Uppercase the input."""
        return text.upper()

    tools = list_registered()
    assert tools[0].description == "Uppercase the input."


def test_decorator_custom_name():
    @tool(description="d", name="my-custom-name")
    async def internal(a: str) -> str:
        return a

    assert list_registered()[0].name == "my-custom-name"


def test_decorator_params_override_wins_over_derivation():
    override = {
        "type": "object",
        "properties": {"custom": {"type": "string", "description": "hand-tuned"}},
        "required": ["custom"],
    }

    @tool(description="d", params_override=override)
    async def hand(a: int, b: int = 0) -> str:
        return "x"

    tools = list_registered()
    assert tools[0].parameters == override


def test_decorator_rejects_sync_function():
    with pytest.raises(TypeError):
        @tool(description="d")
        def not_async(x: str) -> str:
            return x


def test_decorator_requires_description_or_docstring():
    with pytest.raises(ValueError):
        @tool()
        async def nothing(x: str) -> str:
            return x


# ---------------------------------------------------------------------------
# End-to-end registry flow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_registered_tools_run_through_registry():
    from okti.tools.registry import ToolRegistry

    @tool(description="Concat.", risk_level="low")
    async def concat(a: str, b: str) -> str:
        return a + b

    reg = ToolRegistry()
    for td in list_registered():
        reg.register(td)

    out = await reg.call("concat", {"a": "foo", "b": "bar"})
    assert out == "foobar"


def test_list_registered_returns_copy():
    """Callers must not be able to mutate the internal registry."""
    @tool(description="d")
    async def a(x: str) -> str:
        return x

    snapshot = list_registered()
    snapshot.clear()
    # Real registry still has the entry
    assert len(list_registered()) == 1


def test_clear_registered_empties_the_registry():
    @tool(description="d")
    async def a(x: str) -> str:
        return x

    assert len(list_registered()) == 1
    clear_registered()
    assert list_registered() == []
