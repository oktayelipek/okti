"""Session-scoped undo/redo stack for file edits.

Every write-side file tool records the pre-edit content of each affected
path here before the write lands. `undo_edit` restores the most recent
snapshot, moving it to a redo stack; `redo_edit` replays it forward.

Scope
-----
The stack lives in-process for the lifetime of an okti session. It is
NOT persisted across restarts. History is intentionally bounded so a
runaway agent cannot grow memory without limit.

Non-goals
---------
Cross-session persistence, per-file granularity beyond the batch, or git
integration — those belong in dedicated commands, not the undo stack.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Bound on how far back we can undo. Older snapshots are dropped silently.
MAX_HISTORY = 50


@dataclass
class Snapshot:
    """A single reversible edit batch: file paths + their pre-edit content."""

    files: dict[str, str] = field(default_factory=dict)  # abs path → previous content
    label: str = ""


class EditHistory:
    """Bounded undo/redo stack of file-edit snapshots."""

    def __init__(self, max_history: int = MAX_HISTORY) -> None:
        self._undo: deque[Snapshot] = deque(maxlen=max_history)
        self._redo: deque[Snapshot] = deque(maxlen=max_history)

    def push(self, files: dict[str, str], label: str = "") -> None:
        """Record a pre-edit snapshot. Clears the redo stack (linear history)."""
        if not files:
            return
        self._undo.append(Snapshot(files=dict(files), label=label))
        self._redo.clear()

    def undo(self) -> Snapshot | None:
        """Restore the most recent snapshot. Returns the swapped-in "before" state.

        The caller writes each path back to its previous content. We
        capture the *current* content first and push it onto the redo
        stack so redo() can replay forward.
        """
        if not self._undo:
            return None
        snap = self._undo.pop()
        current: dict[str, str] = {}
        for path_str, previous in snap.files.items():
            p = Path(path_str)
            if p.exists():
                try:
                    current[path_str] = p.read_text(encoding="utf-8", errors="replace")
                except OSError as e:
                    logger.warning("Failed to snapshot %s for redo: %s", path_str, e)
                    current[path_str] = previous  # best-effort
            try:
                p.write_text(previous, encoding="utf-8")
            except OSError as e:
                logger.error("Failed to restore %s: %s", path_str, e)
        self._redo.append(Snapshot(files=current, label=snap.label))
        return snap

    def redo(self) -> Snapshot | None:
        """Replay the most recently undone snapshot forward."""
        if not self._redo:
            return None
        snap = self._redo.pop()
        current: dict[str, str] = {}
        for path_str, forward in snap.files.items():
            p = Path(path_str)
            if p.exists():
                try:
                    current[path_str] = p.read_text(encoding="utf-8", errors="replace")
                except OSError as e:
                    logger.warning("Failed to snapshot %s for undo: %s", path_str, e)
                    current[path_str] = forward
            try:
                p.write_text(forward, encoding="utf-8")
            except OSError as e:
                logger.error("Failed to redo %s: %s", path_str, e)
        self._undo.append(Snapshot(files=current, label=snap.label))
        return snap

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()

    def undo_depth(self) -> int:
        return len(self._undo)

    def redo_depth(self) -> int:
        return len(self._redo)


# Process-wide singleton — files.py and TUI both talk to this instance.
_HISTORY = EditHistory()


def get_history() -> EditHistory:
    return _HISTORY


def snapshot_paths(paths: list[Path], label: str = "") -> None:
    """Helper: read each path (if it exists) and push a snapshot batch.

    Missing files are recorded with empty content so undo will re-create
    them as empty; if that's not what you want, call push() directly.
    """
    files: dict[str, str] = {}
    for p in paths:
        try:
            files[str(p)] = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
        except OSError as e:
            logger.warning("Snapshot skipped %s: %s", p, e)
    _HISTORY.push(files, label=label)
