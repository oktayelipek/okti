"""Tests for file tools."""

import os
import pytest
from pathlib import Path
from unittest.mock import patch

# Set workspace env for tests
TEST_DIR = Path(__file__).parent.parent / "test_workspace"
TEST_DIR.mkdir(exist_ok=True)


@pytest.fixture(autouse=True)
def setup_workspace():
    """Create a temporary workspace for file tool tests."""
    os.environ["OKTIGENT_WORKSPACE"] = str(TEST_DIR)
    # Create test files
    (TEST_DIR / "hello.py").write_text("print('hello')\n")
    (TEST_DIR / "multi.txt").write_text("line1\nline2\nline3\nline4\nline5\n")
    yield
    # Cleanup
    for f in TEST_DIR.iterdir():
        f.unlink()
    TEST_DIR.rmdir()


@pytest.mark.asyncio
async def test_read_file():
    from oktigent.tools.files import read_file
    result = await read_file("hello.py")
    assert "print('hello')" in result
    assert "File: hello.py" in result


@pytest.mark.asyncio
async def test_read_file_with_line_range():
    from oktigent.tools.files import read_file
    result = await read_file("multi.txt", start_line=2, end_line=4)
    assert "2: line2" in result
    assert "3: line3" in result
    assert "4: line4" in result


@pytest.mark.asyncio
async def test_write_file():
    from oktigent.tools.files import write_file
    result = await write_file("new_file.txt", "hello world\n")
    assert "File written" in result
    assert (TEST_DIR / "new_file.txt").read_text() == "hello world\n"


@pytest.mark.asyncio
async def test_edit_file():
    from oktigent.tools.files import edit_file
    result = await edit_file("hello.py", "print('hello')", "print('world')")
    assert "File edited" in result
    assert (TEST_DIR / "hello.py").read_text() == "print('world')\n"


@pytest.mark.asyncio
async def test_edit_file_not_found():
    from oktigent.tools.files import edit_file
    result = await edit_file("nonexistent.py", "x", "y")
    assert "Error" in result


@pytest.mark.asyncio
async def test_list_dir():
    from oktigent.tools.files import list_dir
    result = await list_dir(".")
    assert "hello.py" in result
    assert "Directory" in result


@pytest.mark.asyncio
async def test_glob_files():
    from oktigent.tools.files import glob_files
    result = await glob_files("*.py")
    assert "hello.py" in result
