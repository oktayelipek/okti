"""Tests for the atomic multi_file_edit tool.

These tests verify the two-phase behaviour: validation before any write,
and rollback of already-written files if a mid-batch write fails.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from okti.tools.files import multi_file_edit


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("OKTI_WORKSPACE", str(tmp_path))
    return tmp_path


def _write(workspace: Path, name: str, content: str) -> Path:
    p = workspace / name
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_two_file_edit_success(workspace):
    a = _write(workspace, "a.py", "hello world\n")
    b = _write(workspace, "b.py", "spam eggs\n")

    result = await multi_file_edit([
        {"path": "a.py", "edits": [{"old_string": "hello", "new_string": "howdy"}]},
        {"path": "b.py", "edits": [{"old_string": "eggs", "new_string": "bacon"}]},
    ])

    assert "atomically" in result
    assert a.read_text() == "howdy world\n"
    assert b.read_text() == "spam bacon\n"


@pytest.mark.asyncio
async def test_backups_are_cleaned_on_success(workspace):
    _write(workspace, "a.py", "x")
    await multi_file_edit([
        {"path": "a.py", "edits": [{"old_string": "x", "new_string": "y"}]},
    ])
    assert not (workspace / "a.py.okti.bak").exists()


@pytest.mark.asyncio
async def test_multiple_edits_per_file(workspace):
    p = _write(workspace, "a.py", "alpha beta gamma")
    result = await multi_file_edit([
        {"path": "a.py", "edits": [
            {"old_string": "alpha", "new_string": "A"},
            {"old_string": "gamma", "new_string": "G"},
        ]},
    ])
    assert "atomically" in result
    assert p.read_text() == "A beta G"


# ---------------------------------------------------------------------------
# Phase-1 validation aborts before any write
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_file_aborts_all(workspace):
    a = _write(workspace, "a.py", "hello\n")
    result = await multi_file_edit([
        {"path": "a.py", "edits": [{"old_string": "hello", "new_string": "howdy"}]},
        {"path": "does_not_exist.py", "edits": [{"old_string": "x", "new_string": "y"}]},
    ])
    assert "File not found" in result
    # a.py was NOT modified
    assert a.read_text() == "hello\n"
    # no stray backup file either
    assert not (workspace / "a.py.okti.bak").exists()


@pytest.mark.asyncio
async def test_missing_old_string_aborts_all(workspace):
    a = _write(workspace, "a.py", "hello\n")
    b = _write(workspace, "b.py", "world\n")
    result = await multi_file_edit([
        {"path": "a.py", "edits": [{"old_string": "hello", "new_string": "howdy"}]},
        {"path": "b.py", "edits": [{"old_string": "not-in-b", "new_string": "y"}]},
    ])
    assert "old_string not found" in result
    assert "no files were modified" in result.lower()
    assert a.read_text() == "hello\n"
    assert b.read_text() == "world\n"


@pytest.mark.asyncio
async def test_empty_old_string_rejected(workspace):
    a = _write(workspace, "a.py", "hi\n")
    result = await multi_file_edit([
        {"path": "a.py", "edits": [{"old_string": "", "new_string": "y"}]},
    ])
    assert "empty old_string" in result
    assert a.read_text() == "hi\n"


@pytest.mark.asyncio
async def test_empty_operations_rejected():
    result = await multi_file_edit([])
    assert "no operations provided" in result


@pytest.mark.asyncio
async def test_workspace_escape_aborts(workspace):
    _write(workspace, "a.py", "hi\n")
    result = await multi_file_edit([
        {"path": "../../etc/passwd", "edits": [{"old_string": "x", "new_string": "y"}]},
    ])
    assert "escapes workspace" in result


# ---------------------------------------------------------------------------
# Phase-2 rollback on write failure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rollback_when_second_write_fails(workspace, monkeypatch):
    a = _write(workspace, "a.py", "hello\n")
    b = _write(workspace, "b.py", "world\n")

    real_write = Path.write_text
    call_count = {"n": 0}

    def flaky_write_text(self, data, encoding="utf-8", **kw):
        # Fail specifically when writing NEW content to b.py (backup gets ".bak" suffix)
        if self.name == "b.py" and data == "WORLD\n":
            raise OSError("simulated disk full")
        return real_write(self, data, encoding=encoding, **kw)

    with patch.object(Path, "write_text", flaky_write_text):
        result = await multi_file_edit([
            {"path": "a.py", "edits": [{"old_string": "hello", "new_string": "HELLO"}]},
            {"path": "b.py", "edits": [{"old_string": "world", "new_string": "WORLD"}]},
        ])

    assert "Rolled back" in result
    # a.py should have been restored to original
    assert a.read_text() == "hello\n"
    assert b.read_text() == "world\n"
    # Backups cleaned up
    assert not (workspace / "a.py.okti.bak").exists()
    assert not (workspace / "b.py.okti.bak").exists()
