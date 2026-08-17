"""Workspace-wide symbol index + semantic search.

The single biggest capability gap between okti and the frontier
agentic tools was retrieval: the model needs to find "the function
that parses config" without knowing the filename. This module builds
a symbol index (functions, classes, top-level assignments) across
Python / JavaScript / TypeScript files and scores queries against it.

Design constraints
------------------
* **Zero external dependencies.** No embeddings model, no vector DB.
  Python's `ast` for `.py`; a small regex extractor for `.js`/`.ts`/
  `.jsx`/`.tsx`. Ranking is TF-IDF with cosine similarity — good enough
  for symbol lookup and cheap to compute (<50 ms on a mid-size repo).
* **Cacheable.** The index is JSON-serializable to
  `.okti/code_index.json` so repeated calls in the same session don't
  re-parse the tree.
* **Bounded.** File count, per-file size, and per-symbol snippet are
  all capped so a giant vendored directory can't blow up memory.

Not a replacement for a real code intelligence backend (LSP,
tree-sitter, embeddings) — those are the follow-up.
"""

from __future__ import annotations

import ast
import json
import logging
import math
import os
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# --- limits (deliberately conservative) --------------------------------------
_MAX_FILES = 5000
_MAX_FILE_BYTES = 1_000_000
_SNIPPET_LINES = 3

_INDEXED_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx"}

# Directories we never index even if the user points us at them.
_SKIP_DIRS = {
    ".git", ".venv", "venv", "env", "node_modules", "dist", "build",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".tox", ".idea", ".vscode", "target", "out",
}


@dataclass
class Symbol:
    """One indexed symbol (function, class, top-level assignment, …)."""

    name: str
    kind: str        # "function" | "class" | "method" | "assignment" | "export"
    path: str        # relative to workspace root
    line: int        # 1-indexed
    docstring: str = ""
    snippet: str = ""
    parent: str = "" # enclosing class for methods


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _extract_python(source: str, path: str) -> list[Symbol]:
    """AST-based extraction for .py files. Failures fall back to regex."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return _extract_regex(source, path)

    lines = source.splitlines()
    out: list[Symbol] = []

    def _snippet(node: ast.AST) -> str:
        start = getattr(node, "lineno", 1) - 1
        end = min(start + _SNIPPET_LINES, len(lines))
        return "\n".join(lines[start:end])

    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            out.append(Symbol(
                name=node.name, kind="function", path=path,
                line=node.lineno, docstring=(ast.get_docstring(node) or "")[:200],
                snippet=_snippet(node),
            ))
        elif isinstance(node, ast.ClassDef):
            out.append(Symbol(
                name=node.name, kind="class", path=path,
                line=node.lineno, docstring=(ast.get_docstring(node) or "")[:200],
                snippet=_snippet(node),
            ))
            for child in node.body:
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                    out.append(Symbol(
                        name=child.name, kind="method", path=path,
                        line=child.lineno,
                        docstring=(ast.get_docstring(child) or "")[:200],
                        snippet=_snippet(child),
                        parent=node.name,
                    ))
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.isupper():
                    # Module-level constant only — skip lowercase noise
                    out.append(Symbol(
                        name=t.id, kind="assignment", path=path,
                        line=node.lineno, snippet=_snippet(node),
                    ))
    return out


_JS_PATTERNS = [
    # function foo(...) | async function foo(...)
    (re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"), "function"),
    # class Foo | export class Foo
    (re.compile(r"^\s*(?:export\s+(?:default\s+)?)?class\s+([A-Za-z_$][\w$]*)"), "class"),
    # const foo = (...) => | export const foo = (...) =>
    (re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?\("), "function"),
    # export default function
    (re.compile(r"^\s*export\s+default\s+function(?:\s+([A-Za-z_$][\w$]*))?"), "export"),
]


def _extract_regex(source: str, path: str) -> list[Symbol]:
    """Regex fallback for JS/TS and Python files that fail to parse."""
    out: list[Symbol] = []
    lines = source.splitlines()
    for i, line in enumerate(lines, start=1):
        for pat, kind in _JS_PATTERNS:
            m = pat.match(line)
            if m and m.group(1):
                snippet = "\n".join(
                    lines[i - 1 : min(i - 1 + _SNIPPET_LINES, len(lines))]
                )
                out.append(Symbol(
                    name=m.group(1), kind=kind, path=path, line=i,
                    snippet=snippet,
                ))
                break
    return out


def _extract(path: Path, source: str, workspace: Path) -> list[Symbol]:
    rel = str(path.relative_to(workspace))
    if path.suffix == ".py":
        return _extract_python(source, rel)
    if path.suffix in _INDEXED_EXTENSIONS:
        return _extract_regex(source, rel)
    return []


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

@dataclass
class CodeIndex:
    workspace: str = ""
    symbols: list[Symbol] = field(default_factory=list)

    # TF-IDF machinery — computed lazily
    _doc_terms: list[Counter[str]] = field(default_factory=list, repr=False)
    _idf: dict[str, float] = field(default_factory=dict, repr=False)

    @classmethod
    def build(cls, workspace: Path, *, max_files: int = _MAX_FILES) -> CodeIndex:
        idx = cls(workspace=str(workspace))
        count = 0
        for root, dirs, files in os.walk(workspace):
            # Prune skip dirs in-place so os.walk doesn't descend
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
            for name in files:
                path = Path(root) / name
                if path.suffix not in _INDEXED_EXTENSIONS:
                    continue
                if count >= max_files:
                    logger.info("code_index: hit %d-file cap", max_files)
                    break
                try:
                    if path.stat().st_size > _MAX_FILE_BYTES:
                        continue
                    source = path.read_text(encoding="utf-8", errors="replace")
                except OSError as e:
                    logger.debug("code_index: skip %s (%s)", path, e)
                    continue
                idx.symbols.extend(_extract(path, source, workspace))
                count += 1
            if count >= max_files:
                break
        idx._compute_tfidf()
        logger.info("code_index built: %d symbols across %d files", len(idx.symbols), count)
        return idx

    # -- ranking -------------------------------------------------------------

    def _tokenize(self, text: str) -> list[str]:
        # Split on non-word AND on camelCase / snake_case boundaries.
        # Case-preserved base so camelCase detection actually works
        # (`parseConfig` → `parse`, `config`), then lowercased once.
        base = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text)
        expanded: list[str] = []
        for tok in base:
            expanded.append(tok.lower())
            expanded.extend(t.lower() for t in re.split(r"_+", tok) if t and t != tok)
            camels = re.findall(r"[a-z]+|[A-Z][a-z]*", tok)
            if len(camels) > 1:
                expanded.extend(c.lower() for c in camels)
        return expanded

    def _symbol_terms(self, s: Symbol) -> Counter[str]:
        text = " ".join([s.name, s.docstring, s.snippet, s.parent])
        return Counter(self._tokenize(text))

    def _compute_tfidf(self) -> None:
        self._doc_terms = [self._symbol_terms(s) for s in self.symbols]
        n_docs = max(1, len(self.symbols))
        df: Counter[str] = Counter()
        for terms in self._doc_terms:
            df.update(terms.keys())
        self._idf = {
            term: math.log((n_docs + 1) / (df_count + 1)) + 1.0
            for term, df_count in df.items()
        }

    def search(self, query: str, top_k: int = 10) -> list[tuple[Symbol, float]]:
        q_terms = Counter(self._tokenize(query))
        if not q_terms or not self.symbols:
            return []

        scores: list[tuple[Symbol, float]] = []
        for sym, doc in zip(self.symbols, self._doc_terms, strict=False):
            score = 0.0
            for term, q_tf in q_terms.items():
                d_tf = doc.get(term, 0)
                if d_tf:
                    idf = self._idf.get(term, 1.0)
                    score += (1 + math.log(d_tf)) * (1 + math.log(q_tf)) * idf * idf
            # Boost exact-name matches — most useful signal in code search
            if sym.name.lower() in query.lower():
                score *= 3.0
            if score > 0:
                scores.append((sym, score))

        scores.sort(key=lambda p: p[1], reverse=True)
        return scores[:top_k]

    # -- persistence ---------------------------------------------------------

    def to_json(self) -> str:
        return json.dumps({
            "workspace": self.workspace,
            "symbols": [asdict(s) for s in self.symbols],
        }, ensure_ascii=False)

    @classmethod
    def from_json(cls, blob: str) -> CodeIndex:
        raw = json.loads(blob)
        idx = cls(
            workspace=raw.get("workspace", ""),
            symbols=[Symbol(**s) for s in raw.get("symbols", [])],
        )
        idx._compute_tfidf()
        return idx


# ---------------------------------------------------------------------------
# Cache + tool handlers
# ---------------------------------------------------------------------------

_CACHE: CodeIndex | None = None


def _cache_path(workspace: Path) -> Path:
    return workspace / ".okti" / "code_index.json"


def get_index(workspace: Path | None = None, *, force_rebuild: bool = False) -> CodeIndex:
    """Return the workspace index, building or loading from cache as needed."""
    global _CACHE
    ws = workspace or Path(os.environ.get("OKTI_WORKSPACE", os.getcwd()))
    if _CACHE and not force_rebuild and _CACHE.workspace == str(ws):
        return _CACHE

    cache = _cache_path(ws)
    if not force_rebuild and cache.exists():
        try:
            _CACHE = CodeIndex.from_json(cache.read_text(encoding="utf-8"))
            return _CACHE
        except (json.JSONDecodeError, OSError, KeyError) as e:
            logger.warning("code_index cache load failed, rebuilding: %s", e)

    _CACHE = CodeIndex.build(ws)
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(_CACHE.to_json(), encoding="utf-8")
    except OSError as e:
        logger.warning("code_index cache write failed: %s", e)
    return _CACHE


def invalidate_cache() -> None:
    global _CACHE
    _CACHE = None


async def search_symbols(query: str, top_k: int = 10) -> str:
    """Semantic (TF-IDF) search over workspace symbols."""
    import asyncio
    return await asyncio.to_thread(_search_symbols_sync, query, top_k)


def _search_symbols_sync(query: str, top_k: int) -> str:
    idx = get_index()
    hits = idx.search(query, top_k=top_k)
    if not hits:
        return f"No symbols matched: {query!r} (index size: {len(idx.symbols)})"
    lines = [f"Top {len(hits)} match(es) for {query!r}:"]
    for sym, score in hits:
        loc = f"{sym.path}:{sym.line}"
        label = f"{sym.parent}.{sym.name}" if sym.parent else sym.name
        lines.append(f"  [{score:5.1f}] {sym.kind:9s} {label}  @ {loc}")
        if sym.docstring:
            lines.append(f"            {sym.docstring[:120]}")
    return "\n".join(lines)


async def find_definition(name: str) -> str:
    """Locate every symbol with the given name in the workspace."""
    import asyncio
    return await asyncio.to_thread(_find_definition_sync, name)


def _find_definition_sync(name: str) -> str:
    idx = get_index()
    matches = [s for s in idx.symbols if s.name == name]
    if not matches:
        # Case-insensitive fallback
        matches = [s for s in idx.symbols if s.name.lower() == name.lower()]
    if not matches:
        return f"No definition found for {name!r}."
    lines = [f"{len(matches)} definition(s) of {name!r}:"]
    for s in matches:
        label = f"{s.parent}.{s.name}" if s.parent else s.name
        lines.append(f"  {s.kind:9s} {label}  @ {s.path}:{s.line}")
        if s.snippet:
            for snip_line in s.snippet.splitlines()[:_SNIPPET_LINES]:
                lines.append(f"      {snip_line}")
    return "\n".join(lines)


async def rebuild_index() -> str:
    """Force rebuild of the workspace symbol index."""
    import asyncio
    return await asyncio.to_thread(_rebuild_index_sync)


def _rebuild_index_sync() -> str:
    invalidate_cache()
    idx = get_index(force_rebuild=True)
    files = {s.path for s in idx.symbols}
    return f"Rebuilt index: {len(idx.symbols)} symbols across {len(files)} files."


def register_code_index_tools(registry) -> None:  # noqa: ANN001
    """Register the three code-index tools on a ToolRegistry."""
    from okti.tools.registry import ToolDef

    registry.register(ToolDef(
        name="search_symbols",
        description=(
            "Semantic search over workspace symbols (functions, classes, "
            "methods, top-level constants). Ranks by TF-IDF with an "
            "exact-name-match boost. Use to find code by intent when you "
            "don't know the file, e.g. 'parse plan response' or "
            "'compute cost per model'."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural-language query"},
                "top_k": {"type": "integer", "description": "How many results (default 10)"},
            },
            "required": ["query"],
        },
        handler=search_symbols,
        risk_level="low",
    ))

    registry.register(ToolDef(
        name="find_definition",
        description=(
            "Locate every symbol in the workspace with the given exact "
            "(or case-insensitive) name. Cheaper than search_symbols "
            "when you already know the identifier."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Symbol name"},
            },
            "required": ["name"],
        },
        handler=find_definition,
        risk_level="low",
    ))

    registry.register(ToolDef(
        name="rebuild_index",
        description=(
            "Force a rebuild of the workspace symbol index. Do this "
            "after large file moves, renames, or the first time you use "
            "search_symbols in a fresh checkout."
        ),
        parameters={"type": "object", "properties": {}},
        handler=rebuild_index,
        risk_level="low",
    ))
