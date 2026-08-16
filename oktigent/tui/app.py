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
import subprocess
from pathlib import Path
from typing import Any

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widgets import Footer, Input, OptionList, Static
from textual.widgets.option_list import Option

from oktigent.agent.loop import AgentLoop, StreamEvent
from oktigent.config import OktigentConfig
from oktigent.tui.streaming import StreamingMarkdown
from oktigent.tui.slash_commands import SlashCommandHandler

logger = logging.getLogger(__name__)

SLASH_COMMANDS = [
    ("/help", "Show help & command list"),
    ("/setup", "Open onboarding & setup wizard"),
    ("/theme", "Switch color theme (synthwave, matrix, cyberpunk, nord)"),
    ("/rules", "Show active project rules (Cursor, Cline, Copilot, AGENTS.md)"),
    ("/review", "Run AI code review with P0-P3 ranking and SHIP/DO NOT SHIP verdict"),
    ("/plan", "Create a development plan for a goal"),
    ("/approve", "Approve and execute plan tasks"),
    ("/models", "List available models for current provider (supports search filter)"),
    ("/model", "Switch active model (e.g. /model anthropic/claude-3.7-sonnet)"),
    ("/provider", "Switch active model provider"),
    ("/yolo", "Toggle auto-execution without permission prompts"),
    ("/git", "Git operations (status, diff, log, commit, push, branch)"),
    ("/clear", "Clear current chat history"),
    ("/session", "Show active session details"),
    ("/sessions", "List recent saved sessions"),
    ("/save", "Save current session"),
    ("/load", "Load a session by ID"),
    ("/tokens", "Show token usage breakdown"),
    ("/compact", "Force compact older context messages"),
    ("/refresh", "Refresh workspace file tree"),
    ("/mcp", "Manage MCP servers and tools"),
    ("/plugin", "Manage plugins and templates"),
]


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------

class ChatPane(VerticalScroll):
    """Main chat area with streaming support and expressive startup banner."""

    def __init__(self, provider_name: str = "", model_name: str = "", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.provider_name = provider_name
        self.model_name = model_name

    def compose(self) -> ComposeResult:
        from oktigent.tui.animations import AnimatedAsciiBanner
        yield AnimatedAsciiBanner(
            provider_name=self.provider_name,
            model_name=self.model_name,
            id="welcome-banner",
        )

    def add_user_message(self, text: str) -> None:
        msg = Text()
        msg.append("You: ", style="bold cyan")
        msg.append(text)
        self.mount(Static(msg))
        self.scroll_end(animate=False)

    def show_thinking(self, model_name: str) -> None:
        """Mount a live animated thinking indicator."""
        from oktigent.tui.animations import ThinkingIndicator
        self.hide_thinking()
        indicator = ThinkingIndicator(model_name=model_name, id="live-thinking-indicator")
        self.mount(indicator)
        self.scroll_end(animate=False)

    def hide_thinking(self) -> None:
        """Remove any active thinking indicator."""
        try:
            for ind in self.query("#live-thinking-indicator"):
                ind.remove()
        except Exception:
            pass

    async def start_assistant_message(self) -> StreamingMarkdown:
        """Create a new streaming markdown widget for the assistant response."""
        widget = StreamingMarkdown(classes="assistant-message")
        await self.mount(widget)
        self.scroll_end(animate=False)
        return widget

    def add_assistant_message(self, text: str) -> None:
        """Add a complete assistant message (non-streaming fallback)."""
        widget = StreamingMarkdown(classes="assistant-message")
        widget.set_content(text)
        widget.finish()
        self.mount(widget)
        self.scroll_end(animate=False)

    def add_tool_event(self, event: StreamEvent) -> None:
        if event.type == "tool_start":
            style = "bold yellow"
            icon = "⚡"
        elif event.type == "tool_end":
            style = "bold green"
            icon = "✓"
        elif event.type == "tool_denied":
            style = "bold red"
            icon = "✗"
        else:
            style = "dim"
            icon = "✦"

        text = Text()
        text.append(f" {icon} ", style=style)
        text.append(f"{event.tool}", style="bold")
        if event.type == "tool_start" and event.arguments:
            args_summary = _summarize_args(event.arguments)
            if args_summary:
                text.append(f" {args_summary}", style="dim")
        self.mount(Static(text))

        output = getattr(event, "result", getattr(event, "content", ""))
        if event.type == "tool_end" and output:
            result_text = Text()
            lines = output.strip().splitlines()
            preview = lines[0][:100] if lines else ""
            if len(lines) > 1 or (lines and len(lines[0]) > 100):
                preview += f" ... ({len(lines)} lines)"
            result_text.append(f"    └─ {preview}", style="dim")
            self.mount(Static(result_text))

        self.scroll_end(animate=False)

    def add_permission_request(self, tool: str, arguments: dict) -> None:
        text = Text()
        text.append(" ❓ ", style="bold magenta")
        text.append(f"Permission needed: {tool}", style="bold")
        args_summary = _summarize_args(arguments)
        if args_summary:
            text.append(f" {args_summary}", style="dim")
        self.mount(Static(text))
        self.scroll_end(animate=False)

    def add_permission_result(self, tool: str, approved: bool) -> None:
        if approved:
            text = Text(f"   [✓ approved] {tool}", style="bold green")
        else:
            text = Text(f"   [✗ denied]  {tool}", style="bold red")
        self.mount(Static(text))
        self.scroll_end(animate=False)

    def add_status(self, message: str, style: str = "dim") -> None:
        text = Text(message, style=style)
        self.mount(Static(text))
        self.scroll_end(animate=False)


def get_git_info(cwd: Path) -> str:
    """Get compact git branch and uncommitted change count."""
    try:
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(cwd),
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=0.5,
        ).strip()
        status = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=str(cwd),
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=0.5,
        ).strip()
        diff_count = len([line for line in status.splitlines() if line.strip()])
        if diff_count > 0:
            return f"ᚠ {branch} +{diff_count}"
        return f"ᚠ {branch}"
    except Exception:
        return ""


def get_short_cwd(cwd: Path) -> str:
    """Get compact path representation."""
    try:
        home = Path.home()
        rel = cwd.relative_to(home)
        return f"~/{rel}" if len(str(rel)) <= 25 else f".../{cwd.name}"
    except Exception:
        return cwd.name or str(cwd)


class ToolDock(Static):
    """Segmented Powerline HUD bar with model, speed, cwd, git, context window, cost, and live task."""

    state = reactive("idle")
    status_text = reactive("Ready")
    model_text = reactive("")
    speed_text = reactive("")
    cache_pct = reactive(0)
    cost_usd = reactive(0.0)
    tokens_used = reactive(0)
    max_tokens = reactive(200_000)
    current_task = reactive("Ready")
    git_info = reactive("")
    short_cwd = reactive("")

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        self._spinner_idx = 0
        from oktigent.tui.animations import Speedometer
        self.speedometer = Speedometer()
        self._update_env_info()

    def _update_env_info(self) -> None:
        try:
            cwd = Path.cwd()
            self.short_cwd = get_short_cwd(cwd)
            self.git_info = get_git_info(cwd)
        except Exception:
            pass

    def on_mount(self) -> None:
        self.set_interval(0.1, self._spin)
        self.set_interval(3.0, self._update_env_info)

    def _spin(self) -> None:
        from oktigent.tui.animations import BRAILLE_SPINNER
        if self.state in ("thinking", "tool"):
            self._spinner_idx = (self._spinner_idx + 1) % len(BRAILLE_SPINNER)
            if self.speedometer.start_time:
                spd = self.speedometer.speed()
                el = self.speedometer.elapsed()
                if spd > 0:
                    self.speed_text = f"⚡ {spd:.0f}t/s · {el:.1f}s"
                else:
                    self.speed_text = f"⏱️ {el:.1f}s"
            self.refresh()
        else:
            self.refresh()

    def render(self) -> Text:
        from oktigent.tui.animations import BRAILLE_SPINNER
        t = Text()

        # 1. Left corner bracket & Brand (╭─ oktigent 〉)
        t.append("╭─ ", style="bold #22c55e")
        t.append("oktigent", style="bold #38bdf8")
        t.append(" 〉", style="dim #475569")

        # 2. Model (⚙ Opus 4.7 ⚡ · 🔵 high 〉)
        m_str = self.model_text or "Ready"
        if "/" in m_str:
            parts = m_str.split("/")
            m_name = parts[-1]
            display_model = f"⚙ {m_name.strip()} ⚡"
        else:
            display_model = f"⚙ {m_str} ⚡"
        t.append(display_model, style="bold #38bdf8")
        t.append(" 〉", style="dim #475569")

        # 3. Working directory (📁 /path 〉)
        if self.short_cwd:
            t.append(f"📁 {self.short_cwd}", style="#94a3b8")
            t.append(" 〉", style="dim #475569")

        # 4. Git branch & diffs (ᚠ master +2 〉)
        if self.git_info:
            t.append(self.git_info, style="bold #f59e0b")
            t.append(" 〉", style="dim #475569")

        # 5. Context window % & Limit (🪟 1.9%/1M 🪄 〉)
        pct = (self.tokens_used / max(self.max_tokens, 1)) * 100
        if self.max_tokens >= 1_000_000:
            limit_s = f"{self.max_tokens//1_000_000}M"
        else:
            limit_s = f"{self.max_tokens//1000}k"
        
        ctx_info = f"🪟 {pct:.1f}%/{limit_s} 🪄"
        t.append(ctx_info, style="#a78bfa")
        t.append(" 〉", style="dim #475569")

        # 6. Cost USD ($0.26)
        if self.cost_usd == 0.0:
            cost_s = "$0.00"
        elif self.cost_usd < 0.01:
            cost_s = f"${self.cost_usd:.4f}"
        else:
            cost_s = f"${self.cost_usd:.2f}"
        t.append(cost_s, style="bold #fbbf24")

        # 7. Dynamic line and Task/Status at the right (─────── Task ─╮)
        status_disp = ""
        if self.state in ("thinking", "tool"):
            sp = BRAILLE_SPINNER[self._spinner_idx]
            status_disp = f" {sp} {self.status_text} "
        elif self.status_text and self.status_text != "Ready":
            status_disp = f" {self.status_text} "
        elif self.current_task and self.current_task != "Ready":
            status_disp = f" {self.current_task} "

        # Compute remaining terminal width
        current_len = len(t.plain)
        width = self.size.width or 100
        avail = max(3, width - current_len - len(status_disp) - 4)
        line_filler = "─" * avail

        t.append(f" {line_filler}", style="#22c55e")
        if status_disp:
            t.append(status_disp, style="bold #4ade80")
        t.append("─╮", style="bold #22c55e")

        return t

    def set_state(self, new_state: str, tool_name: str = "") -> None:
        self.state = new_state
        if new_state == "thinking":
            self.status_text = "Thinking..."
            self.speedometer.start()
        elif new_state == "tool":
            self.status_text = f"{tool_name}" if tool_name else "Running..."
        elif new_state == "success":
            self.status_text = "Idle"
        elif new_state == "error":
            self.status_text = "Blocked / Error"
        elif new_state == "idle":
            self.status_text = "Ready"
        self.refresh()

    def update_status(self, text: str) -> None:
        self.status_text = text
        self.refresh()

    def update_model(self, text: str) -> None:
        self.model_text = text
        self.refresh()

    def update_tokens(self, usage: Any) -> None:
        if hasattr(usage, "completion_tokens"):
            self.speedometer.add_tokens(usage.completion_tokens)

        self.tokens_used = getattr(usage, "total_tokens", 0)
        self.cost_usd = getattr(usage, "cost_usd", 0.0)

        p_tok = getattr(usage, "prompt_tokens", 0)
        c_read = getattr(usage, "cache_read_tokens", 0)
        if p_tok > 0 and c_read > 0:
            self.cache_pct = int((c_read / p_tok) * 100)
        else:
            self.cache_pct = 0
        self.refresh()


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
        layout: vertical;
        background: #0f111a;
    }
    #chat {
        height: 1fr;
        padding: 1 2;
        overflow-y: auto;
    }
    #command-suggestions {
        display: none;
        max-height: 8;
        background: #181b2a;
        border: round #38bdf8;
        margin: 0 2;
    }
    #bottom-container {
        dock: bottom;
        height: auto;
        layout: vertical;
        background: #0f111a;
    }
    #input-bar {
        height: 3;
        margin: 0 1 0 1;
        padding: 0 1;
        border: round #38bdf8;
        background: #131622;
    }
    #tool-dock {
        height: 1;
        background: transparent;
        margin: 0 1 0 1;
        padding: 0;
        overflow: hidden;
    }
    Footer {
        height: 1;
        background: #111422;
        margin: 0;
    }
    .assistant-message {
        margin: 0 0 1 0;
        height: auto;
        width: 1fr;
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

    def __init__(
        self,
        config: OktigentConfig | None = None,
        resume_session_id: str | None = None,
        force_setup: bool = False,
    ):
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
        self._force_setup = force_setup

    def compose(self) -> ComposeResult:
        # Main expansive chat area
        p_name = self.config.default_provider.value if hasattr(self.config.default_provider, "value") else str(self.config.default_provider)
        m_name = self.config.default_model
        self.chat_pane = ChatPane(provider_name=p_name, model_name=m_name, id="chat")
        yield self.chat_pane

        # Autocomplete suggestions
        self.suggestions_box = OptionList(id="command-suggestions")
        yield self.suggestions_box

        # Bottom container: input prompt + HUD telemetry bar + Footer
        with Vertical(id="bottom-container"):
            self.input_bar = Input(
                placeholder="Type a message or / for commands...",
                id="input-bar",
            )
            yield self.input_bar

            self.tool_dock = ToolDock(id="tool-dock")
            yield self.tool_dock

            yield Footer()

    async def on_mount(self) -> None:
        """Initialize agent on app mount."""
        # Check if onboarding is needed
        from oktigent.tui.onboarding import check_needs_onboarding, OnboardingScreen
        if self._force_setup or check_needs_onboarding():
            self.push_screen(OnboardingScreen(self.config), callback=self._on_onboarding_completed)

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

        # Register permission callback (legacy — now handled via events)
        # self.agent.on("permission_ask", self._handle_permission_request)

        # Set default focus to input bar
        self.input_bar.focus()

    def _on_onboarding_completed(self, updated_config: OktigentConfig | None) -> None:
        """Handle completion of the onboarding screen."""
        if not updated_config:
            self.input_bar.focus()
            return
        self.config = updated_config
        self.agent.config = updated_config
        from oktigent.models.factory import create_provider
        try:
            self.agent.provider = create_provider(updated_config)
            p_name = updated_config.default_provider.value
            m_name = updated_config.default_model
            self.tool_dock.update_model(f"{p_name}/{m_name}")
            self.chat_pane.add_status(
                f"Configuration updated: {p_name} ({m_name}) — Safety: {'Yolo' if updated_config.permissions.yolo else 'Safe'}",
                style="bold green",
            )
        except Exception as e:
            self.chat_pane.add_status(f"Setup error: {e}", style="bold red")

        self.input_bar.focus()

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

    def _show_permission_dialog(self, tool: str, arguments: dict) -> None:
        """Show permission dialog in the TUI."""
        self.chat_pane.add_permission_request(tool, arguments)

    @on(Input.Changed, "#input-bar")
    def on_input_changed(self, event: Input.Changed) -> None:
        """Filter and display slash command suggestions when typing /."""
        val = event.value
        if val.startswith("/"):
            query = val.strip().lower()
            matching = [
                (cmd, desc) for cmd, desc in SLASH_COMMANDS
                if cmd.startswith(query) or query in cmd
            ]
            if matching:
                self.suggestions_box.clear_options()
                for cmd, desc in matching:
                    self.suggestions_box.add_option(Option(f"[bold cyan]{cmd:<10}[/] [dim]— {desc}[/]", id=cmd))
                self.suggestions_box.display = True
                return
        self.suggestions_box.display = False

    @on(OptionList.OptionSelected, "#command-suggestions")
    def on_suggestion_selected(self, event: OptionList.OptionSelected) -> None:
        """Insert selected slash command into input bar."""
        cmd_id = event.option_id
        if cmd_id:
            self.input_bar.value = f"{cmd_id} "
            self.suggestions_box.display = False
            self.input_bar.focus()
            self.input_bar.cursor_position = len(self.input_bar.value)

    @on(Input.Submitted, "#input-bar")
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle user input."""
        self.suggestions_box.display = False
        text = event.value.strip()
        if not text:
            return

        event.input.value = ""

        # Check for slash commands
        if text.startswith("/"):
            # Special approve/deny command when permission dialog is active
            if self._permission_event and not self._permission_event.is_set():
                if text.strip().lower() == "/approve":
                    self._permission_result = True
                    self._permission_event.set()
                    return
                if text.strip().lower() == "/deny":
                    self._permission_result = False
                    self._permission_event.set()
                    return

            handled = await self.slash_handler.handle(text)
            if handled:
                return

        # Show user message
        self.chat_pane.add_user_message(text)

        # Run agent
        self.tool_dock.update_status("Thinking...")
        self._run_agent(text)

    @work(exclusive=True, exit_on_error=False)
    async def _run_agent(self, user_input: str) -> None:
        """Run the agent loop in a worker with live streaming and expressive feedback."""
        model_name = self.config.default_model
        logger.debug("_run_agent started for input: %s", user_input[:80])
        self.chat_pane.show_thinking(model_name)
        stream_widget = None
        accumulated_content = ""
        self.tool_dock.set_state("thinking")

        try:
            event_count = 0
            async for event in self.agent.run_streaming(user_input):
                event_count += 1
                logger.debug("_run_agent event[%d]: type=%s tool=%s content_len=%d",
                    event_count, event.type, event.tool, len(event.content))

                if event.type == "content":
                    if stream_widget is None:
                        self.chat_pane.hide_thinking()
                        stream_widget = await self.chat_pane.start_assistant_message()

                    accumulated_content += event.content
                    stream_widget.append_delta(event.content)

                elif event.type in ("tool_start", "tool_end", "tool_denied"):
                    self.chat_pane.hide_thinking()
                    if event.type == "tool_start":
                        self.tool_dock.set_state("tool", tool_name=event.tool or "tool")
                    elif event.type == "tool_end":
                        self.tool_dock.set_state("thinking")

                    self.chat_pane.add_tool_event(event)

                elif event.type == "permission_ask":
                    self.chat_pane.hide_thinking()
                    self.chat_pane.add_permission_request(event.tool, event.arguments)
                    self.tool_dock.set_state("error")
                    self.tool_dock.update_status(f"Permission needed: {event.tool}")

                    # Wait for user to type /approve or /deny
                    self._permission_event = asyncio.Event()
                    self._permission_result = False
                    await self._permission_event.wait()

                    # Signal the agent loop with the user's decision
                    self.agent._permission_result = self._permission_result
                    self.agent._permission_event.set()

                    if self._permission_result:
                        self.chat_pane.add_permission_result(event.tool, True)
                    else:
                        self.chat_pane.add_permission_result(event.tool, False)

                elif event.type == "turn_end":
                    self.chat_pane.hide_thinking()
                    if stream_widget:
                        stream_widget.finish()
                    if event.usage:
                        self.tool_dock.update_tokens(event.usage)
                    self.tool_dock.set_state("success")
                    if self.config.auto_save:
                        await self._auto_save()

                elif event.type == "compaction":
                    self.chat_pane.add_status(event.content, style="yellow")

            logger.debug("_run_agent loop finished: %d events, accumulated %d chars",
                event_count, len(accumulated_content))
            self.chat_pane.hide_thinking()
            if stream_widget:
                stream_widget.finish()
            elif not accumulated_content:
                logger.warning("_run_agent: no content received from model")
                self.chat_pane.add_status(
                    "Model returned an empty response. This model may not support conversational chat or tool calling.",
                    style="dim yellow",
                )
            self.tool_dock.set_state("idle")

        except Exception as e:
            logger.error("_run_agent exception: %s", e, exc_info=True)
            self.chat_pane.hide_thinking()
            self.chat_pane.add_status(f"Error: {e}", style="bold red")
            self.tool_dock.set_state("error")

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
            new_messages = self.agent.messages[stored_count:]

            for msg in new_messages:
                await storage.add_message(self.agent.session_id, msg)

            await storage.close()
            if new_messages:
                logger.debug("Auto-saved %d new messages for session %s", len(new_messages), self.agent.session_id)

        except Exception as e:
            logger.warning("Auto-save failed: %s", e)
