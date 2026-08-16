"""oktigent TUI — Textual-based terminal user interface.

Layout:
┌──────────────┬──────────────────────┬─────────────┐
│ File Tree     │ Chat / Tool Log      │ Tool Dock   │
│ (collapsible) │ (markdown + stream)  │ (status)    │
├──────────────┼──────────────────────┤             │
│              │                      │             │
│              │   [input bar]        │             │
│              │   /plan /models      │             │
└──────────────┴──────────────────────┴─────────────┘
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widgets import Footer, Header, Input, Label, Static
from textual.worker import WorkerState

from oktigent.agent.loop import AgentLoop, StreamEvent
from oktigent.config import OktigentConfig, PermissionLevel
from oktigent.tui.streaming import StreamingMarkdown
from oktigent.tui.widgets import FileTree, DiffViewer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------

class ChatPane(VerticalScroll):
    """Main chat area with streaming support."""

    def compose(self) -> ComposeResult:
        yield Static(
            "Welcome to [bold cyan]oktigent[/bold cyan]. Type your request below.\n"
            "Type [bold]/help[/bold] for available commands.",
            id="welcome",
        )

    def add_user_message(self, text: str) -> None:
        msg = Text()
        msg.append("You: ", style="bold cyan")
        msg.append(text)
        self.mount(Static(msg))
        self.scroll_end(animate=False)

    def start_assistant_message(self) -> StreamingMarkdown:
        """Create a new streaming markdown widget for the assistant response."""
        widget = StreamingMarkdown(classes="assistant-message")
        self.mount(widget)
        self.scroll_end(animate=False)
        return widget

    def add_assistant_message(self, text: str) -> None:
        """Add a complete assistant message (non-streaming fallback)."""
        widget = StreamingMarkdown(classes="assistant-message")
        widget.set_content(text)
        self.mount(widget)
        self.scroll_end(animate=False)

    def add_tool_event(self, event: StreamEvent) -> None:
        if event.type == "tool_start":
            style = "bold yellow"
            icon = ">>>"
        elif event.type == "tool_end":
            style = "dim green"
            icon = "<<<"
        elif event.type == "tool_denied":
            style = "bold red"
            icon = "!!!"
        else:
            style = "dim"
            icon = "---"

        text = Text()
        text.append(f" {icon} ", style=style)
        text.append(f"{event.tool}", style="bold")
        if event.type == "tool_start" and event.arguments:
            args_summary = _summarize_args(event.arguments)
            if args_summary:
                text.append(f" {args_summary}", style="dim")
        self.mount(Static(text))

        # Show truncated tool result for tool_end
        if event.type == "tool_end" and event.content:
            result_preview = event.content[:500]
            if len(event.content) > 500:
                result_preview += f"\n... ({len(event.content)} chars total)"
            result_text = Text(result_preview, style="dim")
            self.mount(Static(result_text))

        self.scroll_end(animate=False)

    def add_permission_request(self, tool: str, arguments: dict) -> None:
        text = Text()
        text.append(" ??? ", style="bold magenta")
        text.append(f"Permission needed: {tool}", style="bold")
        args_summary = _summarize_args(arguments)
        if args_summary:
            text.append(f" {args_summary}", style="dim")
        self.mount(Static(text))
        self.scroll_end(animate=False)

    def add_permission_result(self, tool: str, approved: bool) -> None:
        if approved:
            text = Text(f"   [approved] {tool}", style="green")
        else:
            text = Text(f"   [denied]  {tool}", style="bold red")
        self.mount(Static(text))
        self.scroll_end(animate=False)

    def add_status(self, message: str, style: str = "dim") -> None:
        text = Text(message, style=style)
        self.mount(Static(text))
        self.scroll_end(animate=False)


class ToolDock(Static):
    """Right panel showing tool activity and status."""

    status_text = reactive("Ready")
    model_text = reactive("")

    def compose(self) -> ComposeResult:
        yield Label("oktigent", id="dock-title")
        yield Static(self.status_text, id="status")
        yield Static(self.model_text, id="model-info")
        yield Static("\nTokens: 0", id="token-display")

    def watch_status_text(self, value: str) -> None:
        try:
            self.query_one("#status", Static).update(value)
        except Exception:
            pass

    def update_status(self, text: str) -> None:
        self.status_text = text

    def update_model(self, text: str) -> None:
        self.model_text = text
        try:
            self.query_one("#model-info", Static).update(text)
        except Exception:
            pass

    def update_tokens(self, usage) -> None:
        try:
            self.query_one("#token-display", Static).update(
                f"Tokens: {usage.total_tokens:,}\n"
                f"Prompt: {usage.prompt_tokens:,}\n"
                f"Completion: {usage.completion_tokens:,}"
            )
        except Exception:
            pass


class PermissionDialog(Vertical):
    """In-line permission approval dialog."""

    def compose(self) -> ComposeResult:
        yield Static("Loading...", id="perm-content")

    def show_request(self, tool: str, arguments: dict) -> None:
        from rich.text import Text
        text = Text()
        text.append(f"\n  Permission: {tool}\n", style="bold yellow")
        args_summary = _summarize_args(arguments)
        if args_summary:
            text.append(f"  Args: {args_summary}\n", style="dim")
        text.append("  [Y] Allow  [N] Deny  [A] Allow all  ", style="bold")
        self.query_one("#perm-content", Static).update(text)

    def show_result(self, approved: bool) -> None:
        if approved:
            self.query_one("#perm-content", Static).update(Text("  [approved]", style="green"))
        else:
            self.query_one("#perm-content", Static).update(Text("  [denied]", style="bold red"))


# ---------------------------------------------------------------------------
# Slash Commands
# ---------------------------------------------------------------------------

class SlashCommandHandler:
    """Handles slash commands from the input."""

    def __init__(self, app: OktigentApp):
        self.app = app

    async def handle(self, command: str) -> bool:
        parts = command.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        handlers = {
            "/help": self._help,
            "/plan": self._plan,
            "/models": self._models,
            "/provider": self._provider,
            "/yolo": self._yolo,
            "/clear": self._clear,
            "/session": self._session,
            "/sessions": self._sessions,
            "/save": self._save,
            "/load": self._load,
            "/tokens": self._tokens,
            "/compact": self._compact,
            "/refresh": self._refresh,
            "/git": self._git,
            "/mcp": self._mcp,
            "/plugin": self._plugin,
        }

        handler = handlers.get(cmd)
        if handler:
            await handler(args)
            return True
        return False

    async def _help(self, args: str) -> None:
        help_text = """## Slash Commands

| Command | Description |
|---------|-------------|
| `/help` | Show this help |
| `/plan <scope>` | Create a development plan |
| `/models` | List available models |
| `/provider <id>` | Switch provider |
| `/yolo` | Toggle yolo mode (bypass permissions) |
| `/clear` | Clear chat history |
| `/session` | Show current session info |
| `/sessions` | List recent sessions |
| `/save` | Save current session |
| `/load <id>` | Load a session by ID |
| `/tokens` | Show token usage |
| `/compact` | Force context compaction |
| `/refresh` | Refresh file tree |
| `/git` | Git operations (status, diff, log, commit) |
| `/mcp` | MCP server management |
| `/plugin` | Plugin management |"""
        self.app.chat_pane.add_assistant_message(help_text)

    async def _plan(self, args: str) -> None:
        if not args:
            self.app.chat_pane.add_status("Usage: /plan <task description>", style="bold red")
            return

        self.app.chat_pane.add_status(f"Creating plan for: {args}...")
        self.app.tool_dock.update_status("Planning...")

        try:
            from oktigent.agent.plan import build_plan_prompt, parse_plan_response
            from oktigent.models.provider import Message, Role

            # Get codebase context
            codebase_context = ""
            try:
                from oktigent.tools.files import list_dir
                codebase_context = await list_dir(".")
            except Exception:
                pass

            prompt = build_plan_prompt(args, codebase_context)
            plan_messages = [
                Message(role=Role.SYSTEM, content=prompt),
                Message(role=Role.USER, content=f"Create a plan for: {args}"),
            ]

            response = await self.app.agent.provider.chat(
                messages=plan_messages,
                model=self.app.config.default_model,
                max_tokens=4000,
            )

            plan = parse_plan_response(response.message.content)
            if plan:
                plan.scope = args
                # Store plan in agent for execution
                self.app.agent._current_plan = plan

                # Display plan
                lines = [f"## Plan: {args}", f"\n{plan.summary}\n", "### Tasks:"]
                for task in plan.tasks:
                    status_icon = "[ ]"
                    deps = f" (depends on: {', '.join(task.dependencies)})" if task.dependencies else ""
                    lines.append(f"- {status_icon} **{task.id}**: {task.title}{deps}")
                    if task.description:
                        lines.append(f"  {task.description[:120]}")
                    if task.files_involved:
                        lines.append(f"  Files: {', '.join(task.files_involved)}")
                lines.append("\nType `/approve` to approve and execute, or edit the plan.")

                self.app.chat_pane.add_assistant_message("\n".join(lines))
            else:
                self.app.chat_pane.add_assistant_message(
                    f"**Raw plan output:**\n\n{response.message.content[:2000]}"
                )

            self.app.tool_dock.update_status("Ready")
        except Exception as e:
            self.app.chat_pane.add_status(f"Plan error: {e}", style="bold red")
            self.app.tool_dock.update_status("Error")
            logger.exception("Plan generation failed")

    async def _models(self, args: str) -> None:
        try:
            from oktigent.models.factory import create_provider
            provider = create_provider(self.app.config)
            models = provider.list_models()
            current = self.app.config.default_model
            lines = [
                f"**Provider:** `{self.app.config.default_provider.value}`",
                f"**Current model:** `{current}`",
                "",
                "**Available models:**",
            ]
            for m in models:
                marker = " (active)" if m == current else ""
                lines.append(f"- `{m}`{marker}")
            self.app.chat_pane.add_assistant_message("\n".join(lines))
        except Exception as e:
            self.app.chat_pane.add_status(f"Error: {e}", style="bold red")

    async def _provider(self, args: str) -> None:
        if not args:
            current = self.app.config.default_provider.value
            self.app.chat_pane.add_assistant_message(
                f"**Current provider:** `{current}`\n\n"
                "Usage: `/provider <ollama|openai|anthropic|gemini|deepseek>`"
            )
            return

        provider_id = args.strip().lower()
        valid = ["ollama", "openai", "anthropic", "gemini", "deepseek", "openrouter", "xai"]
        if provider_id not in valid:
            self.app.chat_pane.add_status(
                f"Unknown provider: {provider_id}. Valid: {', '.join(valid)}",
                style="bold red",
            )
            return

        from oktigent.config import ProviderID
        self.app.config.default_provider = ProviderID(provider_id)

        # Re-create provider
        try:
            from oktigent.models.factory import create_provider
            self.app.agent.provider = create_provider(self.app.config)
            self.app.tool_dock.update_model(f"Provider: {provider_id}")
            self.app.chat_pane.add_status(f"Switched to provider: {provider_id}", style="green")
        except Exception as e:
            self.app.chat_pane.add_status(f"Error switching provider: {e}", style="bold red")

    async def _yolo(self, args: str) -> None:
        self.app.config.permissions.yolo = not self.app.config.permissions.yolo
        state = "ON" if self.app.config.permissions.yolo else "OFF"
        style = "bold yellow" if self.app.config.permissions.yolo else "dim"
        self.app.chat_pane.add_status(f"Yolo mode: {state}", style=style)

    async def _clear(self, args: str) -> None:
        self.app.chat_pane.remove_children()
        self.app.agent.messages = []
        await self.app.agent.initialize()

    async def _session(self, args: str) -> None:
        sid = self.app.agent.session_id or "new"
        msgs = len(self.app.agent.messages)
        model = self.app.config.default_model
        provider = self.app.config.default_provider.value
        auto_save = "ON" if self.app.config.auto_save else "OFF"
        self.app.chat_pane.add_assistant_message(
            f"**Session:** `{sid}`\n"
            f"**Provider:** {provider}\n"
            f"**Model:** `{model}`\n"
            f"**Messages:** {msgs}\n"
            f"**Auto-save:** {auto_save}"
        )

    async def _tokens(self, args: str) -> None:
        usage = self.app.agent.total_usage
        self.app.chat_pane.add_assistant_message(
            f"**Token Usage:**\n"
            f"- Prompt: {usage.prompt_tokens:,}\n"
            f"- Completion: {usage.completion_tokens:,}\n"
            f"- Total: {usage.total_tokens:,}"
        )

    async def _compact(self, args: str) -> None:
        self.app.chat_pane.add_status("Compacting context...")
        self.app.agent.messages = self.app.agent.context.compact_messages(self.app.agent.messages)
        self.app.chat_pane.add_status("Context compacted.", style="green")

    async def _sessions(self, args: str) -> None:
        """List recent sessions with message counts."""
        try:
            from oktigent.storage.db import Storage
            storage = Storage()
            await storage.connect()
            sessions = await storage.list_sessions(limit=10)
            await storage.close()

            if not sessions:
                self.app.chat_pane.add_assistant_message(
                    "No saved sessions yet.\n\n"
                    "Sessions are auto-saved after each turn (disable with `--no-auto-save`).\n"
                    "Use `/save` to save manually."
                )
                return

            lines = ["## Recent Sessions\n"]
            for s in sessions:
                sid = s["id"]
                name = s.get("name", "Unnamed")
                model = s.get("model", "?")
                updated = s.get("updated_at", "?")[:16]
                lines.append(f"- `{sid}` — {name} ({model}) — {updated}")
            lines.append("\nUse `/load <id>` to restore, or start fresh with a new message.")
            self.app.chat_pane.add_assistant_message("\n".join(lines))
        except Exception as e:
            self.app.chat_pane.add_status(f"Error: {e}", style="bold red")

    async def _save(self, args: str) -> None:
        """Save current session (incremental — only saves new messages)."""
        try:
            from oktigent.storage.db import Storage
            storage = Storage()
            await storage.connect()

            if not self.app.agent.session_id:
                self.app.agent.session_id = await storage.create_session(
                    workspace=str(Path.cwd()),
                    model=self.app.config.default_model,
                )

            # Incremental save — only new messages
            stored_count = await storage.get_message_count(self.app.agent.session_id)
            new_messages = self.app.agent.messages[stored_count:]

            for msg in new_messages:
                await storage.add_message(self.app.agent.session_id, msg)

            await storage.close()

            total = len(self.app.agent.messages)
            if new_messages:
                self.app.chat_pane.add_status(
                    f"Session saved: {self.app.agent.session_id} (+{len(new_messages)} new, {total} total)",
                    style="green",
                )
            else:
                self.app.chat_pane.add_status(
                    f"Session {self.app.agent.session_id} — already up to date ({total} messages)",
                    style="dim",
                )
        except Exception as e:
            self.app.chat_pane.add_status(f"Save error: {e}", style="bold red")

    async def _load(self, args: str) -> None:
        """Load a session by ID."""
        if not args:
            self.app.chat_pane.add_status("Usage: /load <session-id>", style="bold red")
            return

        session_id = args.strip()
        try:
            from oktigent.storage.db import Storage
            storage = Storage()
            await storage.connect()
            session = await storage.get_session(session_id)
            if not session:
                self.app.chat_pane.add_status(f"Session not found: {session_id}", style="bold red")
                await storage.close()
                return

            messages = await storage.get_messages(session_id)
            await storage.close()

            # Restore session
            self.app.agent.session_id = session_id
            self.app.agent.messages = messages

            # Refresh chat display
            self.app.chat_pane.remove_children()
            for msg in messages:
                if msg.role.value == "user":
                    self.app.chat_pane.add_user_message(msg.content)
                elif msg.role.value == "assistant" and msg.content:
                    self.app.chat_pane.add_assistant_message(msg.content)

            self.app.chat_pane.add_status(
                f"Session loaded: {session_id} ({len(messages)} messages)", style="green"
            )
        except Exception as e:
            self.app.chat_pane.add_status(f"Load error: {e}", style="bold red")

    async def _refresh(self, args: str) -> None:
        """Refresh file tree."""
        try:
            self.app.file_tree.refresh_tree()
            self.app.chat_pane.add_status("File tree refreshed.", style="green")
        except Exception as e:
            self.app.chat_pane.add_status(f"Refresh error: {e}", style="bold red")

    async def _git(self, args: str) -> None:
        """Git operations."""
        from oktigent.tools.git_tools import (
            git_status, git_diff, git_log, git_add, git_commit,
            git_push, git_branch, git_status_detailed, git_remote_url,
        )

        parts = args.strip().split(maxsplit=1)
        subcmd = parts[0] if parts else "status"
        subargs = parts[1] if len(parts) > 1 else ""

        try:
            if subcmd in ("s", "status", ""):
                result = await git_status_detailed()
            elif subcmd in ("d", "diff"):
                path = subargs if subargs else None
                result = await git_diff(path=path)
            elif subcmd in ("l", "log"):
                count = int(subargs) if subargs.isdigit() else 10
                result = await git_log(count=count)
            elif subcmd in ("a", "add"):
                files = subargs if subargs else "."
                result = await git_add(files)
            elif subcmd in ("c", "commit"):
                if not subargs:
                    result = "Usage: /git commit <message>"
                else:
                    result = await git_commit(subargs)
            elif subcmd in ("p", "push"):
                result = await git_push()
            elif subcmd in ("b", "branch"):
                result = await git_branch()
            elif subcmd == "url":
                result = await git_remote_url()
            elif subcmd == "help":
                result = """## Git Commands

| Command | Description |
|---------|-------------|
| `/git status` | Show detailed status |
| `/git diff` | Show changes |
| `/git log` | Show recent commits |
| `/git add <files>` | Stage files |
| `/git commit <msg>` | Create commit |
| `/git push` | Push to remote |
| `/git branch` | List branches |
| `/git url` | Show remote URL |"""
            else:
                result = f"Unknown git subcommand: {subcmd}. Try /git help"

            self.app.chat_pane.add_assistant_message(f"```\n{result}\n```")
        except Exception as e:
            self.app.chat_pane.add_status(f"Git error: {e}", style="bold red")

    async def _mcp(self, args: str) -> None:
        """MCP server management."""
        parts = args.strip().split(maxsplit=1)
        subcmd = parts[0] if parts else "list"
        subargs = parts[1] if len(parts) > 1 else ""

        if subcmd == "list":
            mcp_client = self.app.agent.mcp_client
            if not mcp_client:
                self.app.chat_pane.add_assistant_message("MCP client not initialized.")
                return
            tools = mcp_client.list_tools()
            if not tools:
                self.app.chat_pane.add_assistant_message("No MCP tools connected.\n\nConfigure servers in `~/.config/oktigent/mcp.toml`")
                return
            lines = ["## MCP Tools\n"]
            for tool in tools:
                lines.append(f"- `{tool.name}` ({tool.server_name}): {tool.description[:80]}")
            self.app.chat_pane.add_assistant_message("\n".join(lines))

        elif subcmd == "help":
            self.app.chat_pane.add_assistant_message("""## MCP Commands

| Command | Description |
|---------|-------------|
| `/mcp list` | List connected MCP tools |
| `/mcp help` | Show this help |

Configure MCP servers in `~/.config/oktigent/mcp.toml`:
```toml
[servers.myserver]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
transport = "stdio"
```""")
        else:
            self.app.chat_pane.add_status(f"Unknown MCP subcommand: {subcmd}. Try /mcp help", style="bold red")

    async def _plugin(self, args: str) -> None:
        """Plugin management."""
        from oktigent.tools.plugin import create_plugin_template, discover_plugins

        parts = args.strip().split(maxsplit=1)
        subcmd = parts[0] if parts else "list"

        if subcmd == "list":
            plugins = discover_plugins()
            if not plugins:
                self.app.chat_pane.add_assistant_message(
                    "No plugins found.\n\n"
                    "Create a plugin in `~/.config/oktigent/plugins/` or `.oktigent/plugins/`\n"
                    "Use `/plugin create` to generate a template."
                )
                return
            lines = ["## Plugins\n"]
            for p in plugins:
                lines.append(f"- `{p.name}`")
            self.app.chat_pane.add_assistant_message("\n".join(lines))

        elif subcmd == "create":
            template_path = create_plugin_template()
            self.app.chat_pane.add_assistant_message(
                f"Plugin template created at:\n`{template_path}`\n\nEdit it to add your custom tools, then restart oktigent."
            )
        elif subcmd == "help":
            self.app.chat_pane.add_assistant_message("""## Plugin Commands

| Command | Description |
|---------|-------------|
| `/plugin list` | List installed plugins |
| `/plugin create` | Create a plugin template |
| `/plugin help` | Show this help |

Plugins are Python files in `~/.config/oktigent/plugins/` or `.oktigent/plugins/`.""")
        else:
            self.app.chat_pane.add_status(f"Unknown plugin subcommand: {subcmd}. Try /plugin help", style="bold red")


def _summarize_args(args: dict) -> str:
    """Create a brief summary of tool arguments."""
    parts = []
    if "path" in args:
        parts.append(str(args["path"]))
    if "command" in args:
        cmd = str(args["command"])
        if len(cmd) > 40:
            cmd = cmd[:37] + "..."
        parts.append(f"`{cmd}`")
    if "pattern" in args:
        parts.append(f"/{args['pattern']}/")
    if "url" in args:
        parts.append(str(args["url"])[:50])
    if "content" in args:
        content = str(args["content"])
        lines = content.count("\n") + 1
        parts.append(f"({len(content)} chars, {lines} lines)")
    if "edits" in args:
        parts.append(f"({len(args['edits'])} edits)")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------

class OktigentApp(App):
    """oktigent TUI application."""

    CSS = """
    Screen {
        layout: horizontal;
    }
    #sidebar {
        width: 20%;
        max-width: 35;
        min-width: 12;
        border-right: solid $primary;
        padding: 1;
    }
    #sidebar Label {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }
    #main {
        width: 60%;
    }
    #chat {
        height: 1fr;
        padding: 1;
        overflow-y: auto;
    }
    #input-bar {
        dock: bottom;
        height: 3;
        padding: 0 1;
        border-top: solid $primary;
    }
    #dock-panel {
        width: 20%;
        max-width: 35;
        min-width: 12;
        border-left: solid $primary;
        padding: 1;
    }
    #dock-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }
    #status {
        margin-top: 1;
    }
    #model-info {
        margin-top: 1;
        color: $secondary;
    }
    #token-display {
        margin-top: 2;
        color: $secondary;
    }
    .assistant-message {
        margin: 0 0 1 0;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit"),
        Binding("ctrl+l", "clear_chat", "Clear"),
        Binding("ctrl+y", "toggle_yolo", "Yolo"),
    ]

    TITLE = "oktigent"
    SUB_TITLE = "agentic coding tool"

    def __init__(self, config: OktigentConfig | None = None, resume_session_id: str | None = None):
        super().__init__()
        self.config = config or OktigentConfig()
        self.agent = AgentLoop(self.config)
        self.slash_handler = SlashCommandHandler(self)
        self.chat_pane: ChatPane
        self.tool_dock: ToolDock
        self.input_bar: Input
        self._current_stream_widget: StreamingMarkdown | None = None
        self._permission_event: asyncio.Event | None = None
        self._permission_result: bool = False
        self._resume_session_id = resume_session_id  # Session to resume on mount

    def compose(self) -> ComposeResult:
        yield Header()

        with Horizontal():
            # Sidebar - file tree
            with Vertical(id="sidebar"):
                yield Label("Files")
                self.file_tree = FileTree(id="file-tree")
                yield self.file_tree

            # Main chat area
            with Vertical(id="main"):
                self.chat_pane = ChatPane(id="chat")
                yield self.chat_pane

                # Input bar
                self.input_bar = Input(
                    placeholder="Type a message or /help...",
                    id="input-bar",
                )
                yield self.input_bar

            # Right dock
            with Vertical(id="dock-panel"):
                self.tool_dock = ToolDock(id="tool-dock")
                yield self.tool_dock

        yield Footer()

    async def on_mount(self) -> None:
        """Initialize agent on app mount."""
        # Resolve session resume if requested
        session_to_load = None
        if self._resume_session_id:
            from oktigent.storage.db import Storage
            storage = Storage()
            await storage.connect()
            if self._resume_session_id == "__latest__":
                session = await storage.get_latest_session(str(Path.cwd()))
                if session:
                    session_to_load = session["id"]
                    self.chat_pane.add_status(f"Resuming session: {session['id']} ({session.get('name', '')})", style="cyan")
                else:
                    self.chat_pane.add_status("No previous session found — starting fresh.", style="dim")
            else:
                session_to_load = self._resume_session_id
            await storage.close()

        await self.agent.initialize(session_id=session_to_load)

        # If we loaded a session, show messages in chat
        if session_to_load:
            await self._show_loaded_messages()

        provider_name = self.config.default_provider.value
        model_name = self.config.default_model
        self.tool_dock.update_model(f"{provider_name}/{model_name}")

        # Register permission callback
        self.agent.on("permission_ask", self._handle_permission_request)

    async def _show_loaded_messages(self) -> None:
        """Display loaded session messages in the chat pane."""
        for msg in self.agent.messages:
            if msg.role.value == "system":
                continue
            if msg.role.value == "user":
                self.chat_pane.add_user_message(msg.content)
            elif msg.role.value == "assistant":
                if msg.content:
                    self.chat_pane.add_assistant_message(msg.content)
                # Show tool calls as events
                for tc in (msg.tool_calls or []):
                    self.chat_pane.add_tool_event(
                        StreamEvent(type="tool_start", tool=tc.name, arguments=tc.arguments)
                    )
            elif msg.role.value == "tool":
                self.chat_pane.add_tool_event(
                    StreamEvent(type="tool_end", tool="tool", content=msg.content[:200])
                )

    def _handle_permission_request(self, tool: str, arguments: dict) -> bool:
        """Handle permission request from agent loop (sync callback -> async bridge)."""
        # This is called from async context via _emit, so we can use asyncio
        self._permission_event = asyncio.Event()
        self._permission_result = False

        # Emit event to TUI
        self.call_from_thread(self._show_permission_dialog, tool, arguments)

        # We need to handle this differently - use a future
        # For now, auto-approve in the callback and let the TUI handle it
        return True

    def _show_permission_dialog(self, tool: str, arguments: dict) -> None:
        """Show permission dialog in the TUI."""
        self.chat_pane.add_permission_request(tool, arguments)

    @on(Input.Submitted, "#input-bar")
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle user input."""
        text = event.value.strip()
        if not text:
            return

        event.input.value = ""

        # Check for slash commands
        if text.startswith("/"):
            # Special approve command
            if text.strip().lower() == "/approve":
                self._permission_result = True
                if self._permission_event:
                    self._permission_event.set()
                return
            if text.strip().lower() == "/deny":
                self._permission_result = False
                if self._permission_event:
                    self._permission_event.set()
                return

            handled = await self.slash_handler.handle(text)
            if handled:
                return

        # Show user message
        self.chat_pane.add_user_message(text)

        # Run agent
        self.tool_dock.update_status("Thinking...")
        self.run_worker(self._run_agent(text), exclusive=True)

    @work(exclusive=True)
    async def _run_agent(self, user_input: str) -> None:
        """Run the agent loop in a worker with live streaming."""
        try:
            # Create streaming widget for this response
            stream_widget = self.chat_pane.start_assistant_message()
            accumulated_content = ""

            async for event in self.agent.run_streaming(user_input):
                if event.type == "content":
                    # Live streaming: append delta to widget
                    accumulated_content += event.content
                    stream_widget.append_delta(event.content)

                elif event.type in ("tool_start", "tool_end", "tool_denied"):
                    self.chat_pane.add_tool_event(event)
                    # Refresh file tree after file modifications
                    if event.type == "tool_end" and event.tool in (
                        "write_file", "edit_file", "multi_edit", "run_command"
                    ):
                        try:
                            self.file_tree.refresh_tree()
                        except Exception:
                            pass

                elif event.type == "permission_ask":
                    # Show permission request and wait for user input
                    self.chat_pane.add_permission_request(event.tool, event.arguments)
                    # Wait for user to type /approve or /deny
                    self._permission_event = asyncio.Event()
                    self._permission_result = False
                    self.tool_dock.update_status(f"Permission needed: {event.tool}")
                    await self._permission_event.wait()

                    if self._permission_result:
                        self.chat_pane.add_permission_result(event.tool, True)
                        # Execute the tool
                        result = await self.agent.registry.call(event.tool, event.arguments)
                        self.chat_pane.add_tool_event(
                            StreamEvent(type="tool_end", tool=event.tool, content=result)
                        )
                        self.agent.messages.append(
                            self.agent.messages.pop()  # Remove pending
                        )
                    else:
                        self.chat_pane.add_permission_result(event.tool, False)

                elif event.type == "turn_end":
                    # Update token display
                    if event.usage:
                        self.tool_dock.update_tokens(event.usage)
                    # Auto-save session after each turn
                    if self.config.auto_save:
                        await self._auto_save()

                elif event.type == "compaction":
                    self.chat_pane.add_status(event.content, style="yellow")

            self.tool_dock.update_status("Ready")

        except Exception as e:
            self.chat_pane.add_status(f"Error: {e}", style="bold red")
            self.tool_dock.update_status("Error")
            logger.exception("Agent loop failed")

    def action_clear_chat(self) -> None:
        self.chat_pane.remove_children()
        self.chat_pane.add_status("Chat cleared.")

    def action_toggle_yolo(self) -> None:
        self.config.permissions.yolo = not self.config.permissions.yolo
        state = "ON" if self.config.permissions.yolo else "OFF"
        style = "bold yellow" if self.config.permissions.yolo else "dim"
        self.chat_pane.add_status(f"Yolo mode: {state}", style=style)

    async def _auto_save(self) -> None:
        """Auto-save session after each assistant turn (silent, no UI feedback).

        Only saves messages that haven't been saved yet (incremental).
        """
        try:
            from oktigent.storage.db import Storage
            storage = Storage()
            await storage.connect()

            if not self.agent.session_id:
                self.agent.session_id = await storage.create_session(
                    workspace=str(Path.cwd()),
                    model=self.config.default_model,
                )

            # Only save new messages (skip already-stored ones)
            stored_count = await storage.get_message_count(self.agent.session_id)
            total = len(self.agent.messages)
            new_messages = self.agent.messages[stored_count:]

            for msg in new_messages:
                await storage.add_message(self.agent.session_id, msg)

            await storage.close()
            if new_messages:
                logger.debug("Auto-saved %d new messages for session %s", len(new_messages), self.agent.session_id)

        except Exception as e:
            logger.warning("Auto-save failed: %s", e)
