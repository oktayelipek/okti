"""Streaming Markdown widget for live content rendering with blinking cursor."""

from __future__ import annotations

import logging

from rich.markdown import Markdown as RichMarkdown
from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static

logger = logging.getLogger(__name__)


class StreamingMarkdown(Static):
    """A Static widget that renders markdown with an animated cursor during streaming."""

    content_text = reactive("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._full_content = ""
        self._is_streaming = True

    def append_delta(self, delta: str) -> None:
        """Append a content delta and re-render with cursor."""
        self._full_content += delta
        self._is_streaming = True
        self._render_content(with_cursor=True)

    def set_content(self, text: str) -> None:
        """Set full content and re-render."""
        self._full_content = text
        self._render_content(with_cursor=self._is_streaming)

    def finish(self) -> None:
        """Mark streaming as finished and render clean markdown without cursor."""
        self._is_streaming = False
        self._render_content(with_cursor=False)

    def _render_content(self, with_cursor: bool = False) -> None:
        """Re-render the markdown content."""
        if not self._full_content:
            return

        display_text = self._full_content + (" ▌" if with_cursor else "")

        try:
            md = RichMarkdown(display_text)
            self.update(md)
            logger.debug("StreamingMarkdown rendered %d chars, size=%s",
                len(self._full_content), self.size)
        except Exception:
            self.update(Text(display_text))
            logger.warning("StreamingMarkdown markdown failed, fell back to Text")

    def clear(self) -> None:
        """Clear the content."""
        self._full_content = ""
        self._is_streaming = False
        self.update("")
