"""Tests for the in-repo tracer / span buffer / JSONL exporter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from okti.telemetry import Tracer, get_tracer


@pytest.fixture
def tracer(tmp_path: Path) -> Tracer:
    t = Tracer()
    t.enable(export_path=tmp_path / "traces.jsonl")
    return t


# ---------------------------------------------------------------------------
# Basic span semantics
# ---------------------------------------------------------------------------

def test_disabled_tracer_is_noop():
    t = Tracer()
    assert not t.is_enabled()
    with t.span("skip") as sp:
        assert sp is None
    assert t.buffer() == []


def test_enabled_span_records_duration_and_attrs(tracer: Tracer):
    with tracer.span("work", key="value") as sp:
        assert sp is not None
        sp.attrs["added"] = 42

    buf = tracer.buffer()
    assert len(buf) == 1
    s = buf[0]
    assert s.name == "work"
    assert s.status == "ok"
    assert s.attrs == {"key": "value", "added": 42}
    assert s.duration_ms >= 0


def test_span_records_exception_and_rethrows(tracer: Tracer):
    with pytest.raises(RuntimeError):
        with tracer.span("boom"):
            raise RuntimeError("kaput")

    buf = tracer.buffer()
    assert len(buf) == 1
    assert buf[0].status == "error"
    assert "kaput" in (buf[0].error or "")


def test_nested_spans_all_recorded(tracer: Tracer):
    with tracer.span("outer"):
        with tracer.span("inner"):
            pass
    names = [s.name for s in tracer.buffer()]
    # `inner` completes first, then `outer`
    assert names == ["inner", "outer"]


# ---------------------------------------------------------------------------
# JSONL export
# ---------------------------------------------------------------------------

def test_jsonl_export_writes_one_line_per_span(tmp_path: Path):
    t = Tracer()
    export = tmp_path / "traces.jsonl"
    t.enable(export_path=export)

    with t.span("a", x=1):
        pass
    with t.span("b", x=2):
        pass

    lines = export.read_text().strip().splitlines()
    assert len(lines) == 2
    payloads = [json.loads(line) for line in lines]
    assert [p["name"] for p in payloads] == ["a", "b"]
    assert payloads[0]["attrs"]["x"] == 1
    assert "duration_ms" in payloads[0]


def test_jsonl_export_appends_across_runs(tmp_path: Path):
    export = tmp_path / "traces.jsonl"

    t1 = Tracer()
    t1.enable(export_path=export)
    with t1.span("first"):
        pass

    t2 = Tracer()
    t2.enable(export_path=export)
    with t2.span("second"):
        pass

    lines = export.read_text().strip().splitlines()
    assert [json.loads(line)["name"] for line in lines] == ["first", "second"]


# ---------------------------------------------------------------------------
# Integration: tool call + permission check emit spans
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tool_call_emits_span(tmp_path: Path, monkeypatch):
    from okti.tools.registry import ToolDef, ToolRegistry

    # Route the module-level tracer to a fresh export path
    module_tracer = get_tracer()
    module_tracer.clear_buffer()
    module_tracer.enable(export_path=tmp_path / "traces.jsonl")

    async def _handler(msg: str = "hi") -> str:
        return f"got {msg}"

    reg = ToolRegistry()
    reg.register(ToolDef(name="echo", description="e", handler=_handler,
                        risk_level="low"))

    out = await reg.call("echo", {"msg": "there"})
    assert "got there" in out

    tool_spans = [s for s in module_tracer.buffer() if s.name.startswith("tool.")]
    assert any(s.name == "tool.echo" and s.attrs.get("risk") == "low"
               for s in tool_spans)


def test_permission_check_emits_span(monkeypatch):
    from okti.agent.permissions import PermissionManager
    from okti.config import OktiConfig
    from okti.tools.registry import ToolDef, ToolRegistry

    module_tracer = get_tracer()
    module_tracer.clear_buffer()
    module_tracer.enable()

    reg = ToolRegistry()
    reg.register(ToolDef(name="safe_read", description="d",
                         handler=None, risk_level="low"))
    pm = PermissionManager(OktiConfig(), reg)
    pm.check("safe_read")

    perm_spans = [s for s in module_tracer.buffer() if s.name == "permission.check"]
    assert perm_spans
    assert perm_spans[-1].attrs["tool"] == "safe_read"
    assert perm_spans[-1].attrs["decision"] == "allow"
