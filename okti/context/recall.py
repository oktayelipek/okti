"""Cross-session conversation recall via TF-IDF over stored messages.

Every message the user or the model has produced already lives in
SQLite. This module makes those searchable so the agent can answer
"how did we do X in a previous session?" without the user having to
find and /load the right session by hand.

Same tokenizer as ``okti/tools/code_index.py`` (camelCase / snake_case
aware). No embeddings, no vector DB — TF-IDF is more than enough for
searching across dozens or hundreds of past turns and lets recall stay
dependency-free.

Design notes
------------
* Runs OFFLINE against the SQLite store — never needs a provider call.
* Snippet is trimmed to a bounded number of chars so a giant assistant
  reply can't dominate the tool result.
* System messages and empty messages are skipped — they're never what
  the user is looking for.
* Results are grouped by session so the agent can decide whether to
  ``/load`` one for full context.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from okti.storage.db import Storage

logger = logging.getLogger(__name__)

# Bounds
_SNIPPET_CHARS = 240
_MAX_MESSAGES = 5000    # cap load; older sessions fall off silently
_DEFAULT_TOP_K = 8


@dataclass
class RecallHit:
    session_id: str
    session_name: str
    session_updated_at: str
    role: str
    content: str
    score: float

    def snippet(self, limit: int = _SNIPPET_CHARS) -> str:
        text = self.content.replace("\n", " ").strip()
        if len(text) <= limit:
            return text
        return text[:limit].rstrip() + "…"


@dataclass
class _Doc:
    """One indexed message with pre-tokenized bag of words."""
    session_id: str
    session_name: str
    session_updated_at: str
    role: str
    content: str
    terms: Counter[str] = field(default_factory=Counter)


# ---------------------------------------------------------------------------
# Tokenizer (mirrors code_index for consistency across memory surfaces)
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    # camelCase splitting must happen BEFORE lowercasing — otherwise
    # `parseConfig` collapses to `parseconfig` and never yields the
    # subtokens `parse` / `config`.
    base = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text or "")
    expanded: list[str] = []
    for tok in base:
        lower = tok.lower()
        expanded.append(lower)
        expanded.extend(t.lower() for t in re.split(r"_+", tok) if t and t != tok)
        camels = re.findall(r"[a-z]+|[A-Z][a-z]*", tok)
        if len(camels) > 1:
            expanded.extend(c.lower() for c in camels)
    return expanded


# ---------------------------------------------------------------------------
# Index build + search
# ---------------------------------------------------------------------------

async def _load_docs(storage: Storage, limit: int = _MAX_MESSAGES) -> list[_Doc]:
    """Pull the most recent N messages joined with their session metadata."""
    cursor = await storage._db.execute(
        """
        SELECT m.session_id, s.name, s.updated_at, m.role, m.content
          FROM messages m
          JOIN sessions s ON s.id = m.session_id
         WHERE m.role != 'system' AND m.content != ''
         ORDER BY m.created_at DESC
         LIMIT ?
        """,
        (limit,),
    )
    rows = await cursor.fetchall()
    docs: list[_Doc] = []
    for session_id, session_name, updated_at, role, content in rows:
        docs.append(_Doc(
            session_id=session_id,
            session_name=session_name or "",
            session_updated_at=updated_at or "",
            role=role,
            content=content or "",
            terms=Counter(_tokenize(content or "")),
        ))
    return docs


def _rank(docs: list[_Doc], query: str, top_k: int) -> list[tuple[_Doc, float]]:
    q_terms = Counter(_tokenize(query))
    if not q_terms or not docs:
        return []

    n_docs = len(docs)
    df: Counter[str] = Counter()
    for doc in docs:
        df.update(doc.terms.keys())
    idf = {
        term: math.log((n_docs + 1) / (df_count + 1)) + 1.0
        for term, df_count in df.items()
    }

    scored: list[tuple[_Doc, float]] = []
    for doc in docs:
        score = 0.0
        for term, q_tf in q_terms.items():
            d_tf = doc.terms.get(term, 0)
            if d_tf:
                w = idf.get(term, 1.0)
                score += (1 + math.log(d_tf)) * (1 + math.log(q_tf)) * w * w
        if score > 0:
            scored.append((doc, score))

    scored.sort(key=lambda p: p[1], reverse=True)
    return scored[:top_k]


async def recall(query: str, top_k: int = _DEFAULT_TOP_K) -> list[RecallHit]:
    """Search every stored non-system message; return the top matches."""
    query = (query or "").strip()
    if not query:
        return []

    storage = Storage()
    await storage.connect()
    try:
        docs = await _load_docs(storage)
    finally:
        await storage.close()

    ranked = _rank(docs, query, top_k=top_k)
    return [
        RecallHit(
            session_id=d.session_id,
            session_name=d.session_name,
            session_updated_at=d.session_updated_at,
            role=d.role,
            content=d.content,
            score=score,
        )
        for d, score in ranked
    ]


# ---------------------------------------------------------------------------
# Tool handler
# ---------------------------------------------------------------------------

async def recall_conversations(query: str, top_k: int = _DEFAULT_TOP_K) -> str:
    """Search past conversations across every saved session."""
    hits = await recall(query, top_k=top_k)
    if not hits:
        return f"No past conversations matched: {query!r}"

    # Group by session so the model can decide which one to /load
    by_session: dict[str, list[RecallHit]] = {}
    for h in hits:
        by_session.setdefault(h.session_id, []).append(h)

    lines = [f"Top {len(hits)} match(es) for {query!r} across "
             f"{len(by_session)} session(s):", ""]
    for session_id, session_hits in by_session.items():
        first = session_hits[0]
        label = first.session_name or session_id
        lines.append(f"### {label}  ({session_id})")
        lines.append(f"_updated {first.session_updated_at[:19]}_")
        lines.append("")
        for h in session_hits:
            lines.append(f"  [{h.score:5.1f}] **{h.role}**: {h.snippet()}")
        lines.append("")
    lines.append(
        "_Use `/load <session_id>` to open one of these sessions in full._"
    )
    return "\n".join(lines)


def register_recall_tools(registry: Any) -> None:
    """Wire recall_conversations into the tool registry."""
    from okti.tools.registry import ToolDef

    registry.register(ToolDef(
        name="recall_conversations",
        description=(
            "Search past conversations across every saved okti session. "
            "TF-IDF over stored user/assistant/tool messages, ranked by "
            "relevance. Use to answer 'how did we handle X before?' "
            "without the user having to find the right session by hand. "
            "Returns snippets grouped by session_id so a /load can pull "
            "one in for full context if needed."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language search query",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Max results (default 8)",
                },
            },
            "required": ["query"],
        },
        handler=recall_conversations,
        risk_level="low",
    ))
