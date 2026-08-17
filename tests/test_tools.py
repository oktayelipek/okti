"""Tests for file tools."""

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def setup_workspace(tmp_path):
    """Create a temporary workspace for file tool tests."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    os.environ["OKTI_WORKSPACE"] = str(workspace)
    # Create test files
    (workspace / "hello.py").write_text("print('hello')\n")
    (workspace / "multi.txt").write_text("line1\nline2\nline3\nline4\nline5\n")
    yield workspace


@pytest.mark.asyncio
async def test_read_file():
    from okti.tools.files import read_file
    result = await read_file("hello.py")
    assert "print('hello')" in result
    assert "File: hello.py" in result


@pytest.mark.asyncio
async def test_read_file_with_line_range():
    from okti.tools.files import read_file
    result = await read_file("multi.txt", start_line=2, end_line=4)
    assert "2: line2" in result
    assert "3: line3" in result
    assert "4: line4" in result


@pytest.mark.asyncio
async def test_write_file():
    from okti.tools.files import write_file
    result = await write_file("new_file.txt", "hello world\n")
    assert "File written" in result
    ws = Path(os.environ["OKTI_WORKSPACE"])
    assert (ws / "new_file.txt").read_text() == "hello world\n"


@pytest.mark.asyncio
async def test_edit_file():
    from okti.tools.files import edit_file
    result = await edit_file("hello.py", "print('hello')", "print('world')")
    assert "File edited" in result
    ws = Path(os.environ["OKTI_WORKSPACE"])
    assert (ws / "hello.py").read_text() == "print('world')\n"


@pytest.mark.asyncio
async def test_edit_file_not_found():
    from okti.tools.files import edit_file
    result = await edit_file("nonexistent.py", "x", "y")
    assert "Error" in result


@pytest.mark.asyncio
async def test_list_dir():
    from okti.tools.files import list_dir
    result = await list_dir(".")
    assert "hello.py" in result
    assert "Directory" in result


@pytest.mark.asyncio
async def test_glob_files():
    from okti.tools.files import glob_files
    result = await glob_files("*.py")
    assert "hello.py" in result
