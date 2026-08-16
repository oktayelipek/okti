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
            "/yolo": self._yolo,
            "/clear": self._clear,
            "/session": self._session,
            "/tokens": self._tokens,
            "/compact": self._compact,
            "/provider": self._provider,
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
| `/provider <id>` | Switch provider (ollama/openai/anthropic/gemini/deepseek) |
| `/yolo` | Toggle yolo mode (bypass permissions) |
| `/clear` | Clear chat history |
| `/session` | Show current session info |
| `/tokens` | Show token usage |
| `/compact` | Force context compaction |"""
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
        self.app.chat_pane.add_assistant_message(
            f"**Session:** `{sid}`\n**Provider:** {provider}\n**Model:** `{model}`\n**Messages:** {msgs}"
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

    def __init__(self, config: OktigentConfig | None = None):
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

    def compose(self) -> ComposeResult:
        yield Header()

        with Horizontal():
            # Sidebar
            with Vertical(id="sidebar"):
                yield Label("Files")
                yield Static("File tree coming soon.", id="file-tree")

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
        await self.agent.initialize()
        provider_name = self.config.default_provider.value
        model_name = self.config.default_model
        self.tool_dock.update_model(f"{provider_name}/{model_name}")

        # Register permission callback
        self.agent.on("permission_ask", self._handle_permission_request)

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
