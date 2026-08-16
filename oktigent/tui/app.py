"""oktigent TUI — Textual-based terminal user interface.

Layout:
┌──────────────┬──────────────────────┬─────────────┐
│ File Tree     │ Chat / Tool Log      │ Tool Dock   │
│ (collapsible) │ (markdown + stream)  │ (status)    │
├──────────────┼──────────────────────┤             │
│ Tabs: Plan / │                      │             │
│ Diff /       │   [input bar]        │             │
│ Session      │   /plan /models      │             │
└──────────────┴──────────────────────┴─────────────┘
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from rich.markdown import Markdown
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widgets import Footer, Header, Input, Label, Static
from textual.worker import WorkerState

from oktigent.agent.loop import AgentLoop, StreamEvent
from oktigent.config import OktigentConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------

class ChatPane(VerticalScroll):
    """Main chat area with streaming support."""

    def compose(self) -> ComposeResult:
        yield Static("Welcome to oktigent. Type your request below.\nType /help for available commands.", id="welcome")

    def add_user_message(self, text: str) -> None:
        with self.app.suspend():
            pass
        msg = Text()
        msg.append("You: ", style="bold cyan")
        msg.append(text)
        self.mount(msg)

    def add_assistant_message(self, text: str) -> None:
        try:
            md = Markdown(text)
            self.mount(md)
        except Exception:
            self.mount(Static(text))
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
            # Show abbreviated args
            args_summary = _summarize_args(event.arguments)
            if args_summary:
                text.append(f" {args_summary}", style="dim")
        self.mount(Static(text))
        self.scroll_end(animate=False)

    def add_status(self, message: str, style: str = "dim") -> None:
        text = Text(message, style=style)
        self.mount(Static(text))
        self.scroll_end(animate=False)


class ToolDock(Static):
    """Right panel showing tool activity and status."""

    status_text = reactive("Ready")

    def compose(self) -> ComposeResult:
        yield Label("oktigent", id="title")
        yield Static(self.status_text, id="status")

    def watch_status_text(self, value: str) -> None:
        self.query_one("#status", Static).update(value)

    def update_status(self, text: str) -> None:
        self.status_text = text


class SlashCommandHandler:
    """Handles slash commands from the input."""

    def __init__(self, app: OktigentApp):
        self.app = app

    async def handle(self, command: str) -> bool:
        """Handle a slash command. Returns True if handled."""
        parts = command.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        handlers = {
            "/help": self._help,
            "/plan": self._plan,
            "/models": self._models,
            "/yolo": self._yolo,
            "/clear": self._clear,
            "/session": self._session,
            "/tokens": self._tokens,
            "/compact": self._compact,
        }

        handler = handlers.get(cmd)
        if handler:
            await handler(args)
            return True
        return False

    async def _help(self, args: str) -> None:
        help_text = """
## Slash Commands

| Command | Description |
|---------|-------------|
| `/help` | Show this help |
| `/plan <scope>` | Create a plan for a task |
| `/models` | List available models |
| `/yolo` | Toggle yolo mode (bypass permissions) |
| `/clear` | Clear chat history |
| `/session` | Show current session info |
| `/tokens` | Show token usage |
| `/compact` | Force context compaction |
"""
        self.app.chat_pane.add_assistant_message(help_text)

    async def _plan(self, args: str) -> None:
        if not args:
            self.app.chat_pane.add_status("Usage: /plan <task description>", style="bold red")
            return
        self.app.chat_pane.add_status(f"Creating plan for: {args}...")
        # TODO: Integrate with plan.py
        self.app.chat_pane.add_assistant_message(
            f"Plan mode for: *{args}*\n\nPlanning not yet integrated. This will generate a task list for your review."
        )

    async def _models(self, args: str) -> None:
        try:
            from oktigent.models.factory import create_provider
            provider = create_provider(self.app.config)
            models = provider.list_models()
            current = self.app.config.default_model
            lines = [f"**Current model:** `{current}`", "", "**Available models:**"]
            for m in models:
                marker = " (active)" if m == current else ""
                lines.append(f"- `{m}`{marker}")
            self.app.chat_pane.add_assistant_message("\n".join(lines))
        except Exception as e:
            self.app.chat_pane.add_status(f"Error: {e}", style="bold red")

    async def _yolo(self, args: str) -> None:
        self.app.config.permissions.yolo = not self.app.config.permissions.yolo
        state = "ON" if self.app.config.permissions.yolo else "OFF"
        self.app.chat_pane.add_status(f"Yolo mode: {state}", style="bold yellow" if self.app.config.permissions.yolo else "dim")

    async def _clear(self, args: str) -> None:
        self.app.chat_pane.remove_children()
        self.app.agent.messages = []
        await self.app.agent.initialize()

    async def _session(self, args: str) -> None:
        sid = self.app.agent.session_id or "new"
        msgs = len(self.app.agent.messages)
        model = self.app.config.default_model
        provider = self.app.config.default_provider.value
        self.app.chat_pane.add_assistant_message(
            f"**Session:** `{sid}`\n**Provider:** {provider}\n**Model:** `{model}`\n**Messages:** {msgs}"
        )

    async def _tokens(self, args: str) -> None:
        usage = self.app.agent.total_usage
        self.app.chat_pane.add_assistant_message(
            f"**Token Usage:**\n- Prompt: {usage.prompt_tokens}\n- Completion: {usage.completion_tokens}\n- Total: {usage.total_tokens}\n- Est. Cost: ${usage.cost_usd:.4f}"
        )

    async def _compact(self, args: str) -> None:
        self.app.chat_pane.add_status("Compacting context...")
        self.app.agent.messages = self.app.agent.context.compact_messages(self.app.agent.messages)
        self.app.chat_pane.add_status("Context compacted.", style="green")


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
        width: 25%;
        max-width: 40;
        min-width: 15;
        border-right: solid $primary;
        padding: 1;
    }
    #sidebar Label {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }
    #main {
        width: 75%;
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
        width: 25%;
        max-width: 40;
        min-width: 15;
        border-left: solid $primary;
        padding: 1;
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

    def __init__(self, config: OktigentConfig | None = None):
        super().__init__()
        self.config = config or OktigentConfig()
        self.agent = AgentLoop(self.config)
        self.slash_handler = SlashCommandHandler(self)
        self.chat_pane: ChatPane
        self.tool_dock: ToolDock
        self.input_bar: Input

    def compose(self) -> ComposeResult:
        yield Header()

        with Horizontal():
            # Sidebar - file tree (placeholder)
            with Vertical(id="sidebar"):
                yield Label("Files")
                yield Static("File tree will appear here.", id="file-tree")

            # Main chat area
            with Vertical(id="main"):
                self.chat_pane = ChatPane(id="chat")
                yield self.chat_pane

                # Input bar
                self.input_bar = Input(placeholder="Type a message or /help...", id="input-bar")
                yield self.input_bar

            # Right dock - tool status
            with Vertical(id="dock-panel"):
                self.tool_dock = ToolDock(id="tool-dock")
                yield self.tool_dock
                yield Static("\nTokens: 0", id="token-display")

        yield Footer()

    async def on_mount(self) -> None:
        """Initialize agent on app mount."""
        await self.agent.initialize()
        self.tool_dock.update_status(f"Model: {self.config.default_model}")

    @on(Input.Submitted, "#input-bar")
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle user input."""
        text = event.value.strip()
        if not text:
            return

        event.input.value = ""

        # Check for slash commands
        if text.startswith("/"):
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
        """Run the agent loop in a worker."""
        try:
            async for event in self.agent.run_streaming(user_input):
                if event.type == "content":
                    # Accumulate for final display
                    pass
                elif event.type in ("tool_start", "tool_end", "tool_denied"):
                    self.chat_pane.add_tool_event(event)
                elif event.type == "turn_end":
                    # Display the accumulated assistant message
                    assistant_msgs = [m for m in self.agent.messages if m.role.value == "assistant"]
                    if assistant_msgs:
                        last = assistant_msgs[-1]
                        if last.content:
                            self.chat_pane.add_assistant_message(last.content)
                    # Update token display
                    usage = self.agent.total_usage
                    self.query_one("#token-display", Static).update(
                        f"Tokens: {usage.total_tokens:,}\nCost: ${usage.cost_usd:.4f}"
                    )
                elif event.type == "compaction":
                    self.chat_pane.add_status(event.content, style="yellow")

            self.tool_dock.update_status("Ready")
        except Exception as e:
            self.chat_pane.add_status(f"Error: {e}", style="bold red")
            self.tool_dock.update_status("Error")
            logger.exception("Agent loop failed")

    def action_clear_chat(self) -> None:
        """Clear the chat pane."""
        self.chat_pane.remove_children()
        self.chat_pane.add_status("Chat cleared.")

    def action_toggle_yolo(self) -> None:
        """Toggle yolo mode."""
        self.config.permissions.yolo = not self.config.permissions.yolo
        state = "ON" if self.config.permissions.yolo else "OFF"
        self.chat_pane.add_status(f"Yolo mode: {state}", style="bold yellow")
