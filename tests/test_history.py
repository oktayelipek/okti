"""Tests for the session-scoped undo/redo edit history."""

from __future__ import annotations

import pytest

from okti.tools.files import (
    edit_file,
    multi_edit,
    multi_file_edit,
    redo_edit,
    undo_edit,
    write_file,
)
from okti.tools.history import EditHistory, get_history


@pytest.fixture(autouse=True)
def _clean_history():
    get_history().clear()
    yield
    get_history().clear()


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("OKTI_WORKSPACE", str(tmp_path))
    return tmp_path


# ---------------------------------------------------------------------------
# Data-structure semantics
# ---------------------------------------------------------------------------

def test_push_empty_is_noop():
    h = EditHistory()
    h.push({}, label="skip")
    assert h.undo_depth() == 0


def test_push_clears_redo_stack(tmp_path):
    h = EditHistory()
    a = tmp_path / "a.txt"
    a.write_text("v1")
    h.push({str(a): "v0"}, label="e1")
    h.undo()  # v1 → v0, redo has "v1"
    assert h.redo_depth() == 1
    # New push clears the redo stack (linear history)
    h.push({str(a): "v2"}, label="e2")
    assert h.redo_depth() == 0


def test_bounded_history(tmp_path):
    h = EditHistory(max_history=3)
    a = tmp_path / "a.txt"
    a.write_text("current")
    for i in range(5):
        h.push({str(a): f"v{i}"}, label=f"e{i}")
    assert h.undo_depth() == 3


# ---------------------------------------------------------------------------
# Integration with file tools
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_write_file_then_undo_creates_original(workspace):
    await write_file("greeting.txt", "hello\n")
    assert (workspace / "greeting.txt").read_text() == "hello\n"
    msg = await undo_edit()
    assert "Undid" in msg
    # Original didn't exist → undo restores to empty
    assert (workspace / "greeting.txt").read_text() == ""


@pytest.mark.asyncio
async def test_write_file_undo_redo_roundtrip(workspace):
    (workspace / "a.py").write_text("original\n")
    await write_file("a.py", "updated\n")
    assert (workspace / "a.py").read_text() == "updated\n"

    await undo_edit()
    assert (workspace / "a.py").read_text() == "original\n"

    await redo_edit()
    assert (workspace / "a.py").read_text() == "updated\n"


@pytest.mark.asyncio
async def test_edit_file_undo_restores_old_content(workspace):
    (workspace / "a.py").write_text("hello world\n")
    await edit_file("a.py", "hello", "howdy")
    assert (workspace / "a.py").read_text() == "howdy world\n"

    await undo_edit()
    assert (workspace / "a.py").read_text() == "hello world\n"


@pytest.mark.asyncio
async def test_multi_edit_undo_restores_original(workspace):
    (workspace / "a.py").write_text("alpha beta gamma")
    await multi_edit("a.py", [
        {"old_string": "alpha", "new_string": "A"},
        {"old_string": "gamma", "new_string": "G"},
    ])
    assert (workspace / "a.py").read_text() == "A beta G"

    await undo_edit()
    assert (workspace / "a.py").read_text() == "alpha beta gamma"


@pytest.mark.asyncio
async def test_multi_file_edit_undo_restores_all_files(workspace):
    (workspace / "a.py").write_text("hello\n")
    (workspace / "b.py").write_text("world\n")

    await multi_file_edit([
        {"path": "a.py", "edits": [{"old_string": "hello", "new_string": "HELLO"}]},
        {"path": "b.py", "edits": [{"old_string": "world", "new_string": "WORLD"}]},
    ])
    assert (workspace / "a.py").read_text() == "HELLO\n"
    assert (workspace / "b.py").read_text() == "WORLD\n"

    await undo_edit()
    assert (workspace / "a.py").read_text() == "hello\n"
    assert (workspace / "b.py").read_text() == "world\n"


@pytest.mark.asyncio
async def test_undo_when_empty_reports_nothing():
    msg = await undo_edit()
    assert "Nothing to undo" in msg


@pytest.mark.asyncio
async def test_redo_after_new_edit_reports_nothing(workspace):
    (workspace / "a.py").write_text("v0")
    await write_file("a.py", "v1")
    await undo_edit()  # back to v0, redo now has v1
    await write_file("a.py", "v2")  # new edit — clears redo
    msg = await redo_edit()
    assert "Nothing to redo" in msg


@pytest.mark.asyncio
async def test_multiple_undos_walk_backward(workspace):
    p = workspace / "log.txt"
    p.write_text("v0")
    await write_file("log.txt", "v1")
    await write_file("log.txt", "v2")
    await write_file("log.txt", "v3")

    assert p.read_text() == "v3"
    await undo_edit()
    assert p.read_text() == "v2"
    await undo_edit()
    assert p.read_text() == "v1"
    await undo_edit()
    assert p.read_text() == "v0"
    msg = await undo_edit()
    assert "Nothing to undo" in msg
