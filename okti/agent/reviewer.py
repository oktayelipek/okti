"""Smart Code Reviewer — Ranks issues from P0 (Blocker) to P3 (Nit) and issues a clear SHIP / DO NOT SHIP verdict."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from okti.models.provider import BaseProvider, Message, Role

logger = logging.getLogger(__name__)


@dataclass
class ReviewFinding:
    """A specific code review issue with severity score."""
    severity: str  # "P0", "P1", "P2", "P3"
    file: str
    line: int | None
    title: str
    description: str
    suggestion: str


@dataclass
class ReviewVerdict:
    """Final code review outcome and actionable checklist."""
    verdict: str  # "SHIP" or "DO NOT SHIP"
    score: int  # 0 to 100
    summary: str
    findings: list[ReviewFinding] = field(default_factory=list)


_REVIEW_SYSTEM_PROMPT = """You are an elite Senior Staff Principal Code Reviewer.
Analyze the provided Git diff and changed files with extreme precision.

Classify all findings into strict severity tiers:
- P0: RELEASE BLOCKER (Security hole, data loss risk, regression, crash, broken auth) -> Leads to DO NOT SHIP
- P1: HIGH (Significant bug, edge-case failure, missing error handling, performance leak)
- P2: MEDIUM (Code smell, missing test, architectural inconsistency, non-idiomatic pattern)
- P3: LOW / NIT (Naming, typo, micro-optimization, docstring enhancement)

Output JSON only in this exact format:
```json
{
  "verdict": "SHIP" | "DO NOT SHIP",
  "score": 85,
  "summary": "High-level summary of code quality and release readiness.",
  "findings": [
    {
      "severity": "P0" | "P1" | "P2" | "P3",
      "file": "path/to/file.py",
      "line": 42,
      "title": "Brief title",
      "description": "Why this is an issue",
      "suggestion": "How to fix it"
    }
  ]
}
```
"""


async def perform_code_review(
    provider: BaseProvider,
    model: str,
    git_diff: str,
    context: str = "",
) -> ReviewVerdict:
    """Execute AI-driven code review on active changes."""
    if not git_diff.strip():
        return ReviewVerdict(
            verdict="SHIP",
            score=100,
            summary="No uncommitted or staged changes detected in the workspace.",
            findings=[],
        )

    user_prompt = f"### Changes to Review:\n\n```diff\n{git_diff[:25000]}\n```\n"
    if context:
        user_prompt += f"\n### Additional Context:\n{context[:5000]}\n"

    messages = [
        Message(role=Role.SYSTEM, content=_REVIEW_SYSTEM_PROMPT),
        Message(role=Role.USER, content=user_prompt),
    ]

    try:
        resp = await provider.chat(
            messages=messages,
            model=model,
            temperature=0.1,
            max_tokens=4000,
        )
        content = resp.message.content

        # Parse JSON
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        raw_json = json_match.group(1) if json_match else content.strip()
        data = json.loads(raw_json)

        findings = [
            ReviewFinding(
                severity=f.get("severity", "P2"),
                file=f.get("file", "unknown"),
                line=f.get("line"),
                title=f.get("title", ""),
                description=f.get("description", ""),
                suggestion=f.get("suggestion", ""),
            )
            for f in data.get("findings", [])
        ]

        return ReviewVerdict(
            verdict=data.get("verdict", "SHIP"),
            score=data.get("score", 90),
            summary=data.get("summary", "Review complete."),
            findings=findings,
        )
    except Exception as e:
        logger.exception("Code review failed")
        return ReviewVerdict(
            verdict="DO NOT SHIP",
            score=0,
            summary=f"Automated review failed: {e}",
            findings=[],
        )


def render_review_markdown(verdict: ReviewVerdict) -> str:
    """Format ReviewVerdict into rich, structured markdown."""
    icon = "🚀" if verdict.verdict == "SHIP" else "🛑"

    lines = [
        f"## {icon} Code Review Verdict: **[{verdict.verdict}]** (Score: {verdict.score}/100)\n",
        f"> {verdict.summary}\n",
    ]

    if not verdict.findings:
        lines.append("✨ **No critical issues found.** All changes look ready to ship!")
        return "\n".join(lines)

    lines.append("### 📋 Review Findings\n")
    lines.append("| Severity | File | Line | Issue | Suggestion |")
    lines.append("|---|---|---|---|---|")

    for f in verdict.findings:
        line_str = str(f.line) if f.line is not None else "-"
        lines.append(f"| **{f.severity}** | `{f.file}` | {line_str} | {f.title} | {f.suggestion} |")

    return "\n".join(lines)
