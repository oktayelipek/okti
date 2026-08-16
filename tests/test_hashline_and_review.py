"""Tests for Hashline editing engine, Dual Model Advisor, and Smart Code Reviewer."""

import pytest
from pathlib import Path

from oktigent.tools.hashline import (
    HashAnchorEdit,
    apply_hash_edits,
    compute_line_hash,
    render_hash_anchored_lines,
)
from oktigent.tools.files import hash_edit_file, read_file
from oktigent.agent.reviewer import ReviewFinding, ReviewVerdict, render_review_markdown
from oktigent.agent.advisor import AdvisorNote


def test_compute_line_hash():
    h1 = compute_line_hash("def hello():")
    h2 = compute_line_hash("  def hello():  ")  # normalized whitespace
    assert h1 == h2
    assert len(h1) == 3


def test_render_hash_anchored_lines():
    code = "def foo():\n    return 42"
    anchored = render_hash_anchored_lines(code, start_line=10)
    assert len(anchored) == 2
    assert ":10]" in anchored[0]
    assert "def foo():" in anchored[0]
    assert ":11]" in anchored[1]


def test_apply_hash_edits_success():
    orig = "def add(a, b):\n    return a - b\n"
    # Find hash for return line
    ret_hash = compute_line_hash("    return a - b")
    
    edits = [
        HashAnchorEdit(
            start_anchor=f"{ret_hash}:2",
            end_anchor=f"{ret_hash}:2",
            replacement="    return a + b\n",
        )
    ]
    ok, new_content, err = apply_hash_edits(orig, edits)
    assert ok
    assert "return a + b" in new_content
    assert "return a - b" not in new_content


def test_apply_hash_edits_mismatch_fails_safely():
    orig = "def add(a, b):\n    return a + b\n"
    edits = [
        HashAnchorEdit(
            start_anchor="xyz:2",  # non-existent hash
            end_anchor="xyz:2",
            replacement="    return 0\n",
        )
    ]
    ok, new_content, err = apply_hash_edits(orig, edits)
    assert not ok
    assert "not found or hash diverged" in err
    assert new_content == orig  # original preserved


@pytest.mark.asyncio
async def test_hash_edit_file_tool(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OKTIGENT_WORKSPACE", str(tmp_path))
    file_path = tmp_path / "calc.py"
    file_path.write_text("def mul(a, b):\n    return a / b\n", encoding="utf-8")

    # Read with hash anchors
    anchored_text = await read_file("calc.py", hash_anchored=True)
    assert "def mul(a, b):" in anchored_text

    # Extract hash for line 2
    h = compute_line_hash("    return a / b")
    res = await hash_edit_file("calc.py", edits=[
        {
            "start_anchor": f"{h}:2",
            "end_anchor": f"{h}:2",
            "replacement": "    return a * b\n",
        }
    ])
    assert "Successfully applied" in res
    assert "return a * b" in file_path.read_text(encoding="utf-8")


def test_render_review_markdown():
    verdict = ReviewVerdict(
        verdict="DO NOT SHIP",
        score=45,
        summary="Security vulnerability found.",
        findings=[
            ReviewFinding(
                severity="P0",
                file="auth.py",
                line=12,
                title="SQL Injection",
                description="Raw string formatting in SQL query",
                suggestion="Use parameterized query",
            )
        ]
    )
    rendered = render_review_markdown(verdict)
    assert "DO NOT SHIP" in rendered
    assert "P0" in rendered
    assert "SQL Injection" in rendered


def test_advisor_note_dataclass():
    note = AdvisorNote(
        level="blocker",
        title="Unsafe eval",
        message="Using eval on user input is hazardous.",
        fix_hint="Use ast.literal_eval",
    )
    assert note.level == "blocker"
    assert note.fix_hint == "Use ast.literal_eval"
