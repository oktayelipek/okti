"""File tree widget — shows workspace directory structure in the sidebar."""

from __future__ import annotations

import os
from pathlib import Path

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static, Tree
from textual.widgets.tree import TreeNode


class FileTree(Static):
    """Interactive file tree for the sidebar."""

    selected_path = reactive("")

    def __init__(self, workspace: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self.workspace = Path(workspace or os.environ.get("OKTI_WORKSPACE", os.getcwd()))

    def compose(self):
        tree: Tree[str] = Tree(str(self.workspace.name), id="file-tree-view")
        tree.root.expand()
        self._build_tree(tree.root, self.workspace)
        yield tree

    def _build_tree(self, node: TreeNode, path: Path, max_depth: int = 4, current_depth: int = 0) -> None:
        """Recursively build the file tree."""
        if current_depth >= max_depth:
            return

        try:
            entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            return

        # Ignore patterns
        ignore = {
            "__pycache__", ".git", "node_modules", ".venv", "venv",
            ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
            ".eggs", "*.egg-info",
        }

        for entry in entries:
            if entry.name.startswith(".") and entry.name not in (".github",):
                continue
            if entry.name in ignore or any(entry.name.endswith(ext) for ext in (".pyc", ".pyo")):
                continue

            if entry.is_dir():
                child = node.add_leaf(
                    f"  {entry.name}/",
                    data=str(entry.relative_to(self.workspace)),
                )
                self._build_tree(child, entry, max_depth, current_depth + 1)
            else:
                size = entry.stat().st_size
                if size < 1024:
                    size_str = f"{size}B"
                elif size < 1024 * 1024:
                    size_str = f"{size / 1024:.0f}K"
                else:
                    size_str = f"{size / (1024 * 1024):.1f}M"

                # Color by extension
                ext = entry.suffix.lower()
                icon = self._get_icon(ext)

                node.add_leaf(
                    f"  {icon} {entry.name} ({size_str})",
                    data=str(entry.relative_to(self.workspace)),
                )

    def _get_icon(self, ext: str) -> str:
        """Get an icon for a file extension."""
        icons = {
            ".py": "PY",
            ".js": "JS",
            ".ts": "TS",
            ".tsx": "TX",
            ".jsx": "JX",
            ".rs": "RS",
            ".go": "GO",
            ".rb": "RB",
            ".java": "JV",
            ".c": "C ",
            ".cpp": "C+",
            ".h": "H ",
            ".md": "MD",
            ".toml": "TL",
            ".yaml": "YL",
            ".yml": "YL",
            ".json": "JS",
            ".sh": "SH",
            ".ps1": "PS",
            ".html": "HT",
            ".css": "CS",
            ".sql": "SQ",
            ".txt": "TX",
        }
        return icons.get(ext, "  ")

    def refresh_tree(self) -> None:
        """Refresh the file tree."""
        from textual.css.query import NoMatches
        try:
            tree = self.query_one("#file-tree-view", Tree)
        except NoMatches:
            return
        tree.root.remove_children()
        tree.root.label = str(self.workspace.name)
        self._build_tree(tree.root, self.workspace)

    def get_selected_path(self) -> str | None:
        """Get the currently selected file path."""
        from textual.css.query import NoMatches
        try:
            tree = self.query_one("#file-tree-view", Tree)
        except NoMatches:
            return None
        if tree.cursor_node and tree.cursor_node.data:
            return tree.cursor_node.data
        return None


class DiffViewer(Static):
    """Inline diff viewer for showing file changes."""

    def show_diff(self, file_path: str, old_content: str, new_content: str) -> None:
        """Display a unified diff."""
        import difflib

        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        diff = list(difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
            lineterm="",
        ))

        if not diff:
            self.update("No changes")
            return

        # Build colored diff
        text = Text()
        for line in diff[:100]:  # Cap at 100 lines
            if line.startswith("+++") or line.startswith("---"):
                text.append(line + "\n", style="bold")
            elif line.startswith("@@"):
                text.append(line + "\n", style="cyan")
            elif line.startswith("+"):
                text.append(line + "\n", style="green")
            elif line.startswith("-"):
                text.append(line + "\n", style="red")
            else:
                text.append(line + "\n")

        if len(diff) > 100:
            text.append(f"\n... ({len(diff)} lines total, showing first 100)\n", style="dim")

        self.update(text)

    def show_file(self, file_path: str, content: str, highlight_line: int | None = None) -> None:
        """Display file contents with optional line highlighting."""
        lines = content.splitlines()
        text = Text()
        for i, line in enumerate(lines[:200], start=1):
            line_num = f"{i:4d}: "
            if highlight_line and i == highlight_line:
                text.append(line_num, style="bold yellow")
                text.append(line + "\n", style="on dark_green")
            else:
                text.append(line_num, style="dim")
                text.append(line + "\n")

        if len(lines) > 200:
            text.append(f"\n... ({len(lines)} lines total)\n", style="dim")

        self.update(text)
