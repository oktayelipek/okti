"""Hashline — Hash-anchored surgical file editing engine.

Computes stable short hashes for every line of code so models can reference
content anchors instead of ambiguous line numbers or fragile exact-string matches.
Prevents whitespace mismatch loops, line drift, and token waste.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


def compute_line_hash(line: str) -> str:
    """Compute a deterministic 3-character hash of normalized line content."""
    # Normalize leading/trailing whitespace for noise-free hashing
    normalized = re.sub(r"\s+", " ", line.strip())
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return digest[:3]


def render_hash_anchored_lines(content: str, start_line: int = 1) -> list[str]:
    """Return lines formatted with line number and 3-char hash anchor: [a1f:1] def hello():"""
    lines = content.splitlines()
    output = []
    for i, line in enumerate(lines, start=start_line):
        h = compute_line_hash(line)
        output.append(f"[{h}:{i}] {line}")
    return output


@dataclass
class HashAnchorEdit:
    """A replacement targeting an anchor range [start_anchor..end_anchor]."""
    start_anchor: str  # e.g., "a1f:10" or "a1f"
    end_anchor: str    # e.g., "b2c:15" or "b2c"
    replacement: str


def apply_hash_edits(content: str, edits: list[HashAnchorEdit]) -> tuple[bool, str, str]:
    """Apply hash-anchored edits to content safely.

    Returns:
        (success, new_content, error_message)
    """
    lines = content.splitlines(keepends=True)

    # Helper to parse anchor
    def parse_anchor(anchor_str: str) -> tuple[str | None, int | None]:
        anchor_str = anchor_str.strip().strip("[]")
        if ":" in anchor_str:
            parts = anchor_str.split(":", 1)
            h = parts[0].strip().lower()
            try:
                line_no = int(parts[1].strip())
                return h, line_no
            except ValueError:
                return h, None
        return anchor_str.lower(), None

    current_lines = list(lines)

    for edit_idx, edit in enumerate(edits, start=1):
        s_hash, s_line = parse_anchor(edit.start_anchor)
        e_hash, e_line = parse_anchor(edit.end_anchor)

        # Locate start line index (0-based)
        start_idx = None
        if s_line is not None and 1 <= s_line <= len(current_lines):
            line_content = current_lines[s_line - 1]
            if s_hash is None or compute_line_hash(line_content) == s_hash:
                start_idx = s_line - 1

        if start_idx is None and s_hash:
            for idx, line in enumerate(current_lines):
                if compute_line_hash(line) == s_hash:
                    start_idx = idx
                    break

        if start_idx is None:
            return False, content, f"Edit #{edit_idx}: Start anchor '{edit.start_anchor}' not found or hash diverged."

        # Locate end line index (0-based)
        end_idx = None
        if e_line is not None and 1 <= e_line <= len(current_lines) and e_line - 1 >= start_idx:
            line_content = current_lines[e_line - 1]
            if e_hash is None or compute_line_hash(line_content) == e_hash:
                end_idx = e_line - 1

        if end_idx is None and e_hash:
            for idx in range(start_idx, len(current_lines)):
                if compute_line_hash(current_lines[idx]) == e_hash:
                    end_idx = idx
                    break

        if end_idx is None:
            return False, content, f"Edit #{edit_idx}: End anchor '{edit.end_anchor}' not found after start anchor."

        # Build replacement lines with proper linebreaks
        rep = edit.replacement
        if rep and not rep.endswith("\n"):
            rep += "\n"
        rep_lines = [r + "\n" for r in rep.splitlines()] if rep.strip() else []

        # Apply splice
        current_lines[start_idx : end_idx + 1] = rep_lines

    return True, "".join(current_lines), ""
