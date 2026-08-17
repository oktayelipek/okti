"""Tests for OTel wiring and configure_telemetry() bootstrap."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from okti.config import OktiConfig, TelemetryConfig
from okti.telemetry import Tracer, configure_telemetry, get_tracer


def _reset_singleton():
    """Reset the module-level tracer between tests."""
    t = get_tracer()
    t.disable()
    t.clear_buffer()
    t._otel_tracer = None
    t._export_path = None


@pytest.fixture(autouse=True)
def _isolated_tracer():
    _reset_singleton()
    yield
    _reset_singleton()


# ---------------------------------------------------------------------------
# span() must yield exactly once — even with OTel + JSONL both on
# ---------------------------------------------------------------------------

def test_span_yields_once_with_otel_and_jsonl(tmp_path: Path):
    tracer = Tracer()
    tracer.enable(export_path=tmp_path / "traces.jsonl")

    # Fake OTel tracer that behaves like start_as_current_span
    class FakeOtelSpan:
        def __init__(self):
            self.attrs = {}
            self.status = None
            self.exception = None
        def set_attribute(self, k, v): self.attrs[k] = v
        def record_exception(self, e): self.exception = e
        def set_status(self, s): self.status = s

    class FakeCM:
        def __init__(self, span): self.span = span
        def __enter__(self): return self.span
        def __exit__(self, *_): return False

    fake_span = FakeOtelSpan()
    fake_otel = MagicMock()
    fake_otel.start_as_current_span.return_value = FakeCM(fake_span)
    tracer._otel_tracer = fake_otel

    yields = 0
    with tracer.span("work", foo="bar") as sp:
        yields += 1
        assert sp is fake_span
    assert yields == 1

    # Both OTel attribute set and JSONL span emitted
    assert fake_span.attrs == {"foo": "bar"}
    assert len(tracer.buffer()) == 1
    assert tracer.buffer()[0].name == "work"


def test_span_yields_once_otel_only():
    tracer = Tracer()
    # Not enabled — OTel only

    class FakeOtelSpan:
        def set_attribute(self, k, v): pass
        def record_exception(self, e): pass
        def set_status(self, s): pass

    class FakeCM:
        def __enter__(self): return FakeOtelSpan()
        def __exit__(self, *_): return False

    fake_otel = MagicMock()
    fake_otel.start_as_current_span.return_value = FakeCM()
    tracer._otel_tracer = fake_otel

    yields = 0
    with tracer.span("otel-only") as sp:
        yields += 1
        assert sp is not None
    assert yields == 1
    # JSONL disabled → nothing buffered
    assert tracer.buffer() == []


def test_span_records_exception_on_both_paths(tmp_path: Path):
    tracer = Tracer()
    tracer.enable(export_path=tmp_path / "t.jsonl")

    fake_span = MagicMock()
    fake_otel = MagicMock()
    fake_otel.start_as_current_span.return_value.__enter__.return_value = fake_span
    fake_otel.start_as_current_span.return_value.__exit__.return_value = False
    tracer._otel_tracer = fake_otel

    with pytest.raises(ValueError):
        with tracer.span("bad"):
            raise ValueError("nope")

    # Home-grown span captured the error
    buf = tracer.buffer()
    assert len(buf) == 1
    assert buf[0].status == "error"
    assert "nope" in (buf[0].error or "")
    # OTel span also recorded the exception
    fake_span.record_exception.assert_called_once()


# ---------------------------------------------------------------------------
# configure_telemetry()
# ---------------------------------------------------------------------------

def test_configure_enables_jsonl_when_config_says_so(tmp_path: Path):
    cfg = OktiConfig(telemetry=TelemetryConfig(
        enabled=True,
        export_path=tmp_path / "t.jsonl",
    ))
    configure_telemetry(cfg)
    assert get_tracer().is_enabled()


def test_configure_is_noop_without_endpoint_and_disabled():
    cfg = OktiConfig(telemetry=TelemetryConfig(enabled=False))
    configure_telemetry(cfg)
    assert not get_tracer().is_enabled()


def test_configure_uses_env_var_endpoint_when_config_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    calls: dict = {}

    fake_otel_trace = types.SimpleNamespace()
    fake_provider = MagicMock()
    fake_otel_trace.get_tracer_provider = MagicMock(return_value=object())
    fake_otel_trace.set_tracer_provider = MagicMock(side_effect=lambda p: calls.setdefault("provider", p))
    fake_otel_trace.get_tracer = MagicMock(return_value=MagicMock())

    class FakeExporter:
        def __init__(self, endpoint): calls["endpoint"] = endpoint

    class FakeBatch:
        def __init__(self, exporter): calls["exporter"] = exporter

    class FakeProvider:
        def __init__(self, resource=None): calls["resource"] = resource
        def add_span_processor(self, p): calls["processor"] = p

    class FakeResource:
        @staticmethod
        def create(attrs): return {"resource": attrs}

    def install(name, module):
        monkeypatch.setitem(sys.modules, name, module)

    install("opentelemetry", types.SimpleNamespace(trace=fake_otel_trace))
    install("opentelemetry.trace", fake_otel_trace)
    install(
        "opentelemetry.exporter.otlp.proto.grpc.trace_exporter",
        types.SimpleNamespace(OTLPSpanExporter=FakeExporter),
    )
    install(
        "opentelemetry.sdk.resources",
        types.SimpleNamespace(Resource=FakeResource),
    )
    install(
        "opentelemetry.sdk.trace",
        types.SimpleNamespace(TracerProvider=FakeProvider),
    )
    install(
        "opentelemetry.sdk.trace.export",
        types.SimpleNamespace(BatchSpanProcessor=FakeBatch),
    )

    cfg = OktiConfig(telemetry=TelemetryConfig(service_name="okti-test"))
    configure_telemetry(cfg)

    assert calls["endpoint"] == "http://localhost:4317"
    assert calls["resource"] == {"resource": {"service.name": "okti-test"}}


def test_configure_skips_if_tracer_provider_already_installed(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")

    class FakeProviderClass: ...
    existing = FakeProviderClass()

    fake_trace = types.SimpleNamespace(
        get_tracer_provider=MagicMock(return_value=existing),
        set_tracer_provider=MagicMock(),
        get_tracer=MagicMock(return_value=MagicMock()),
    )

    def install(name, module):
        monkeypatch.setitem(sys.modules, name, module)

    install("opentelemetry", types.SimpleNamespace(trace=fake_trace))
    install("opentelemetry.trace", fake_trace)
    install(
        "opentelemetry.exporter.otlp.proto.grpc.trace_exporter",
        types.SimpleNamespace(OTLPSpanExporter=MagicMock()),
    )
    install(
        "opentelemetry.sdk.resources",
        types.SimpleNamespace(Resource=MagicMock()),
    )
    install(
        "opentelemetry.sdk.trace",
        types.SimpleNamespace(TracerProvider=FakeProviderClass),
    )
    install(
        "opentelemetry.sdk.trace.export",
        types.SimpleNamespace(BatchSpanProcessor=MagicMock()),
    )

    configure_telemetry(OktiConfig())

    fake_trace.set_tracer_provider.assert_not_called()
    # But cached tracer handle was still refreshed
    assert get_tracer()._otel_tracer is not None


def test_configure_handles_missing_otel_sdk(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    # Force the SDK import to fail
    for name in list(sys.modules):
        if name.startswith("opentelemetry"):
            monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setitem(sys.modules, "opentelemetry", None)

    # Should not raise
    configure_telemetry(OktiConfig())


def test_configure_prefers_config_endpoint_over_env(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://env-endpoint")
    captured_endpoint = {}

    class FakeExporter:
        def __init__(self, endpoint): captured_endpoint["v"] = endpoint

    class FakeBatch:
        def __init__(self, exporter): pass

    class FakeProvider:
        def __init__(self, resource=None): pass
        def add_span_processor(self, p): pass

    fake_trace = types.SimpleNamespace(
        get_tracer_provider=MagicMock(return_value=object()),
        set_tracer_provider=MagicMock(),
        get_tracer=MagicMock(return_value=MagicMock()),
    )

    def install(name, module):
        monkeypatch.setitem(sys.modules, name, module)

    install("opentelemetry", types.SimpleNamespace(trace=fake_trace))
    install("opentelemetry.trace", fake_trace)
    install(
        "opentelemetry.exporter.otlp.proto.grpc.trace_exporter",
        types.SimpleNamespace(OTLPSpanExporter=FakeExporter),
    )
    install(
        "opentelemetry.sdk.resources",
        types.SimpleNamespace(Resource=types.SimpleNamespace(create=lambda a: a)),
    )
    install(
        "opentelemetry.sdk.trace",
        types.SimpleNamespace(TracerProvider=FakeProvider),
    )
    install(
        "opentelemetry.sdk.trace.export",
        types.SimpleNamespace(BatchSpanProcessor=FakeBatch),
    )

    configure_telemetry(OktiConfig(telemetry=TelemetryConfig(
        otlp_endpoint="http://config-endpoint",
    )))
    assert captured_endpoint["v"] == "http://config-endpoint"
