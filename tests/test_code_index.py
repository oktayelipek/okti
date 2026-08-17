"""Tests for the workspace code index and semantic search."""

from __future__ import annotations

import pytest

from okti.tools.code_index import (
    CodeIndex,
    find_definition,
    get_index,
    invalidate_cache,
    search_symbols,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    invalidate_cache()
    yield
    invalidate_cache()


@pytest.fixture
def sample_workspace(tmp_path, monkeypatch):
    (tmp_path / "app.py").write_text('''
"""Top-level module."""

MAX_TOKENS = 128000

def parse_config(path: str) -> dict:
    """Load and validate a TOML config."""
    return {}

class ConfigLoader:
    """Reads and normalizes config files."""

    def load(self, path: str) -> dict:
        """Load from disk."""
        return {}

    def save(self, data: dict) -> None:
        pass
''')

    (tmp_path / "utils.py").write_text('''
def compute_cost(model: str, tokens: int) -> float:
    """Estimate USD cost for a completion."""
    return 0.0

def unused_helper():
    pass
''')

    (tmp_path / "web.js").write_text('''
export function renderPage() {}
class DomBinder {}
const clickHandler = async () => {};
''')

    # Skip directories the walker must prune
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk.js").write_text("export function junk(){}")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "site.py").write_text("def junk(): pass")

    monkeypatch.setenv("OKTI_WORKSPACE", str(tmp_path))
    return tmp_path


# ---------------------------------------------------------------------------
# Build / parse
# ---------------------------------------------------------------------------

def test_build_extracts_python_functions_and_classes(sample_workspace):
    idx = CodeIndex.build(sample_workspace)
    names = {s.name for s in idx.symbols}
    assert "parse_config" in names
    assert "ConfigLoader" in names
    assert "compute_cost" in names
    assert "MAX_TOKENS" in names        # module constant
    assert "load" in names               # method
    assert "save" in names               # method


def test_methods_carry_parent_class(sample_workspace):
    idx = CodeIndex.build(sample_workspace)
    load = next(s for s in idx.symbols if s.name == "load" and s.kind == "method")
    assert load.parent == "ConfigLoader"


def test_build_extracts_js(sample_workspace):
    idx = CodeIndex.build(sample_workspace)
    js = [s for s in idx.symbols if s.path == "web.js"]
    names = {s.name for s in js}
    assert "renderPage" in names
    assert "DomBinder" in names
    assert "clickHandler" in names


def test_build_skips_vendored_dirs(sample_workspace):
    idx = CodeIndex.build(sample_workspace)
    paths = {s.path for s in idx.symbols}
    assert not any("node_modules" in p for p in paths)
    assert not any(".venv" in p for p in paths)


def test_docstrings_captured(sample_workspace):
    idx = CodeIndex.build(sample_workspace)
    pc = next(s for s in idx.symbols if s.name == "parse_config")
    assert "TOML" in pc.docstring


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def test_search_ranks_exact_name_first(sample_workspace):
    idx = CodeIndex.build(sample_workspace)
    hits = idx.search("parse_config")
    assert hits[0][0].name == "parse_config"


def test_search_by_intent_finds_by_docstring(sample_workspace):
    idx = CodeIndex.build(sample_workspace)
    hits = idx.search("estimate cost")
    top_names = [h[0].name for h in hits[:3]]
    assert "compute_cost" in top_names


def test_search_by_intent_finds_class_by_docstring(sample_workspace):
    idx = CodeIndex.build(sample_workspace)
    hits = idx.search("normalize toml config")
    top_names = [h[0].name for h in hits[:3]]
    assert "ConfigLoader" in top_names or "parse_config" in top_names


def test_search_returns_nothing_for_gibberish(sample_workspace):
    idx = CodeIndex.build(sample_workspace)
    hits = idx.search("zzzz_does_not_exist_qqqq")
    assert hits == []


def test_search_respects_top_k(sample_workspace):
    idx = CodeIndex.build(sample_workspace)
    hits = idx.search("config", top_k=2)
    assert len(hits) <= 2


# ---------------------------------------------------------------------------
# Persistence & cache
# ---------------------------------------------------------------------------

def test_json_roundtrip(sample_workspace):
    idx = CodeIndex.build(sample_workspace)
    reloaded = CodeIndex.from_json(idx.to_json())
    assert len(reloaded.symbols) == len(idx.symbols)
    # Ranking still works after reload
    hits = reloaded.search("parse_config")
    assert hits[0][0].name == "parse_config"


def test_get_index_writes_cache(sample_workspace):
    idx = get_index(sample_workspace)
    cache = sample_workspace / ".okti" / "code_index.json"
    assert cache.exists()
    assert len(idx.symbols) > 0


def test_get_index_reads_cache(sample_workspace):
    # First call builds + writes
    get_index(sample_workspace)
    invalidate_cache()
    # Second call loads from disk — no rebuild
    idx2 = get_index(sample_workspace)
    assert any(s.name == "parse_config" for s in idx2.symbols)


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_symbols_tool_output(sample_workspace):
    out = await search_symbols("parse_config")
    assert "parse_config" in out
    assert "app.py" in out


@pytest.mark.asyncio
async def test_find_definition_tool_output(sample_workspace):
    out = await find_definition("ConfigLoader")
    assert "ConfigLoader" in out
    assert "app.py" in out


@pytest.mark.asyncio
async def test_find_definition_case_insensitive(sample_workspace):
    out = await find_definition("configloader")
    assert "ConfigLoader" in out


@pytest.mark.asyncio
async def test_search_symbols_no_hits_message(sample_workspace):
    out = await search_symbols("qqq_absolutely_nothing_matches_zzz")
    assert "No symbols matched" in out
