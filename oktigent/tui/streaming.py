"""Streaming Markdown widget for live content rendering with blinking cursor."""

from __future__ import annotations

import logging

from rich.console import Console
from rich.markdown import Markdown as RichMarkdown
from rich.segment import Segment
from rich.text import Text
from textual.widgets import Static

logger = logging.getLogger(__name__)


def _markdown_to_text(md_text: str, width: int = 100) -> Text:
    """Pre-render Markdown into a styled Rich `Text` for reliable display.

    Markdown is rendered through a Rich console and captured as a `Text`
    object so the streaming cursor can be appended as plain text and the
    content displays reliably inside a `Static` widget.
    """
    md = RichMarkdown(md_text)
    console = Console(
        width=max(40, width),
        force_terminal=False,
        color_system="standard",
        highlight=False,
    )
    text = Text()
    for seg in console.render(md):
        if isinstance(seg, Segment):
            text.append(seg.text, style=seg.style)
        else:
            text.append(str(seg))
    text.rstrip()
    return text


class StreamingMarkdown(Static):
    """A Static widget that renders markdown with an animated cursor during streaming."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._full_content = ""
        self._is_streaming = True

    def append_delta(self, delta: str) -> None:
        """Append a content delta and re-render with cursor."""
        self._full_content += delta
        self._is_streaming = True
        self._update_display(with_cursor=True)

    def set_content(self, text: str) -> None:
        """Set full content and re-render."""
        self._full_content = text
        self._update_display(with_cursor=self._is_streaming)

    def finish(self) -> None:
        """Mark streaming as finished and render clean markdown without cursor."""
        self._is_streaming = False
        self._update_display(with_cursor=False)

    def _update_display(self, with_cursor: bool = False) -> None:
        """Re-render the markdown content.

        NOTE: this must NOT be named ``_render_content`` — that name is a
        private method on Textual's ``Static`` base class which the compositor
        calls to produce the widget's strips. Overriding it silently broke
        rendering entirely (the response was never drawn to the screen).
        """
        if not self._full_content:
            return

        display_text = self._full_content + (" ▌" if with_cursor else "")

        try:
            text = _markdown_to_text(display_text, width=self.size.width or 100)
            self.update(text)
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
