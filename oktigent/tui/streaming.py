"""Streaming Markdown widget for live content rendering.

Instead of creating a new Markdown widget per response, this widget
accumulates content deltas and re-renders in place.
"""

from __future__ import annotations

from rich.markdown import Markdown as RichMarkdown
from textual.reactive import reactive
from textual.widgets import Static


class StreamingMarkdown(Static):
    """A Static widget that renders markdown and updates incrementally."""

    content_text = reactive("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._full_content = ""

    def append_delta(self, delta: str) -> None:
        """Append a content delta and re-render."""
        self._full_content += delta
        self._render_content()

    def set_content(self, text: str) -> None:
        """Set full content and re-render."""
        self._full_content = text
        self._render_content()

    def _render_content(self) -> None:
        """Re-render the markdown content."""
        if not self._full_content:
            return
        try:
            md = RichMarkdown(self._full_content)
            self.update(md)
        except Exception:
            self.update(self._full_content)

    def clear(self) -> None:
        """Clear the content."""
        self._full_content = ""
        self.update("")
