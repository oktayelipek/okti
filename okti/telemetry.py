"""Lightweight tracing for tool calls, provider requests, permissions.

The frontier agentic tools ship OTLP/OpenTelemetry out of the box so
teams can point Grafana/Jaeger/Datadog at them. okti stays
dependency-free by default: a tiny in-repo `Tracer` writes JSON lines
to `.okti/traces.jsonl`. An optional OTel bridge is picked up
automatically when `opentelemetry-api` is importable, so users on
`pip install okti[otel]` get real OTLP export with zero code changes.

Span shape (one line per span in the JSONL file):

    {
      "name": "tool.run_command",
      "start": 1723890123.456,
      "duration_ms": 42.1,
      "attrs": {"tool": "run_command", "risk": "destructive"},
      "status": "ok" | "error",
      "error": "..."           # only if status == "error"
    }

The tracer is a no-op unless `Tracer.enable()` is called (or the
`OKTI_TRACE=1` env var is set before import). That keeps the hot path
free of overhead for users who don't opt in.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Span:
    name: str
    start: float
    duration_ms: float = 0.0
    attrs: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "start": self.start,
            "duration_ms": round(self.duration_ms, 3),
            "attrs": self.attrs,
            "status": self.status,
        }
        if self.error:
            d["error"] = self.error
        return d


class Tracer:
    """Process-wide tracer. Disabled by default — call enable() to start."""

    def __init__(self) -> None:
        self._enabled = False
        self._export_path: Path | None = None
        self._lock = threading.Lock()
        self._buffer: list[Span] = []
        self._otel_tracer: Any = None
        # Bring up OTel if the library is importable — silent no-op otherwise
        self._maybe_wire_otel()

    def _maybe_wire_otel(self) -> None:
        try:
            from opentelemetry import trace
        except ImportError:
            return
        self._otel_tracer = trace.get_tracer("okti")

    def enable(self, export_path: Path | None = None) -> None:
        """Turn tracing on. Writes to .okti/traces.jsonl by default."""
        self._enabled = True
        self._export_path = export_path or (
            Path(os.environ.get("OKTI_WORKSPACE", os.getcwd())) / ".okti" / "traces.jsonl"
        )
        try:
            self._export_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning("Tracer cannot create export dir: %s", e)

    def disable(self) -> None:
        self._enabled = False

    def is_enabled(self) -> bool:
        return self._enabled

    def buffer(self) -> list[Span]:
        """Return a snapshot of the in-memory span buffer (test hook)."""
        with self._lock:
            return list(self._buffer)

    def clear_buffer(self) -> None:
        with self._lock:
            self._buffer.clear()

    @contextmanager
    def span(self, name: str, **attrs: Any):
        """Context manager that records a span even when disabled (no-op)."""
        if not self._enabled and self._otel_tracer is None:
            yield None
            return

        # OTel path — delegate to real tracer if wired
        if self._otel_tracer is not None:
            with self._otel_tracer.start_as_current_span(name) as otel_span:
                for k, v in attrs.items():
                    otel_span.set_attribute(k, str(v))
                try:
                    yield otel_span
                except Exception as e:
                    otel_span.record_exception(e)
                    otel_span.set_status(_otel_error_status(str(e)))
                    raise
            if not self._enabled:
                return

        # Home-grown path
        span = Span(name=name, start=time.time(), attrs=dict(attrs))
        t0 = time.perf_counter()
        try:
            yield span
        except Exception as e:
            span.status = "error"
            span.error = f"{type(e).__name__}: {e}"[:500]
            raise
        finally:
            span.duration_ms = (time.perf_counter() - t0) * 1000.0
            self._emit(span)

    def _emit(self, span: Span) -> None:
        with self._lock:
            self._buffer.append(span)
        if not self._export_path:
            return
        try:
            with open(self._export_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(span.to_dict(), ensure_ascii=False) + "\n")
        except OSError as e:
            logger.debug("Trace write failed: %s", e)


def _otel_error_status(msg: str) -> Any:
    from opentelemetry.trace import Status, StatusCode
    return Status(StatusCode.ERROR, msg)


# ---------------------------------------------------------------------------
# Singleton + convenience
# ---------------------------------------------------------------------------

_TRACER = Tracer()

if os.environ.get("OKTI_TRACE", "").lower() in ("1", "true", "yes"):
    _TRACER.enable()


def get_tracer() -> Tracer:
    return _TRACER


def span(name: str, **attrs: Any):
    """Shortcut: `with span("foo", key=val): ...`."""
    return _TRACER.span(name, **attrs)
