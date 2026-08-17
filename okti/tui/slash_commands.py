"""Slash commands — extracted from app.py for maintainability."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from okti.tui.app import OktiApp

logger = logging.getLogger(__name__)


class SlashCommandHandler:
    """Handles slash commands from the input."""

    def __init__(self, app: OktiApp):
        self.app = app

    async def handle(self, command: str) -> bool:
        parts = command.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        handlers = {
            "/help": self._help,
            "/theme": self._theme,
            "/rules": self._rules,
            "/review": self._review,
            "/setup": self._setup,
            "/onboard": self._setup,
            "/plan": self._plan,
            "/budget": self._budget,           # type: ignore[attr-defined]
            "/prompt": self._prompt,           # type: ignore[attr-defined]
            "/profile": self._profile,         # type: ignore[attr-defined]
            "/plans": self._plans,             # type: ignore[attr-defined]
            "/plan-resume": self._plan_resume, # type: ignore[attr-defined]
            "/approve": self._approve,
            "/models": self._models,
            "/model": self._model,
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

    async def _rules(self, args: str) -> None:
        """Display all universal project rules detected in workspace."""
        from okti.agent.rules import load_universal_rules, render_rules_markdown
        rules = load_universal_rules()
        self.app.chat_pane.add_assistant_message(render_rules_markdown(rules))

    async def _review(self, args: str) -> None:
        """Run smart code review on git changes with P0-P3 ranking and SHIP verdict."""
        self.app.chat_pane.add_status("Running code review on workspace changes...", style="bold cyan")
        self.app.tool_dock.update_status("Reviewing...")
        try:
            from okti.tools.vfs import resolve_virtual_uri
            diff_text = await resolve_virtual_uri("diff://")

            from okti.agent.reviewer import perform_code_review, render_review_markdown
            verdict = await perform_code_review(
                provider=self.app.agent.provider,
                model=self.app.config.default_model,
                git_diff=diff_text,
            )
            self.app.chat_pane.add_assistant_message(render_review_markdown(verdict))
            self.app.tool_dock.update_status("Ready")
        except Exception as e:
            self.app.chat_pane.add_status(f"Review error: {e}", style="bold red")
            self.app.tool_dock.update_status("Error")

    async def _help(self, args: str) -> None:
        help_text = """## Slash Commands

| Command | Description |
|---------|-------------|
| `/help` | Show this help |
| `/theme <name>` | Change visual theme (`default`, `synthwave`, `matrix`, `cyberpunk`, `nord`) |
| `/setup` | Open onboarding & configuration wizard |
| `/plan <scope>` | Create a development plan |
| `/approve` | Approve and execute plan tasks |
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
| `/git <subcmd>` | Git operations (status, diff, log, commit, push, branch) |
| `/mcp <list|help>` | MCP server management |
| `/plugin <list|create|help>` | Plugin management |"""
        self.app.chat_pane.add_assistant_message(help_text)

    async def _theme(self, args: str) -> None:
        """Switch visual color theme."""
        theme_name = args.strip().lower()
        from okti.tui.animations import THEMES
        if not theme_name or theme_name not in THEMES:
            names = ", ".join(f"`{k}`" for k in THEMES.keys())
            self.app.chat_pane.add_status(f"Available themes: {names}\nUsage: `/theme <name>`", style="cyan")
            return

        try:
            css = THEMES[theme_name]
            self.app.screen.styles.parse(css, read_from=("user", "theme"))
            self.app.chat_pane.add_status(f"Theme switched to {theme_name.upper()}!", style="bold green")
        except Exception:
            self.app.chat_pane.add_status(f"Theme change applied: {theme_name}", style="green")

    async def _setup(self, args: str) -> None:
        """Launch the setup wizard modal."""
        from okti.tui.onboarding import OnboardingScreen
        self.app.push_screen(OnboardingScreen(self.app.config), callback=self.app._on_onboarding_completed)

    async def _approve(self, args: str) -> None:
        """Approve and execute tasks from current plan."""
        plan = self.app.agent._current_plan
        if not plan:
            self.app.chat_pane.add_status("No active plan to approve. Use /plan <scope> first.", style="dim")
            return

        pending = plan.pending_tasks()
        if not pending:
            self.app.chat_pane.add_status("All tasks in the plan are already completed.", style="green")
            return

        task = pending[0]
        from okti.agent.plan import TaskStatus, build_task_prompt
        task.status = TaskStatus.IN_PROGRESS
        await _persist_plan(self.app.agent, plan)
        # Surface the running-total cost preview so the user can bail out early.
        self.app.chat_pane.add_status(
            f"Estimate for remaining plan: {plan.cost_summary(self.app.config.default_model)}",
            style="dim cyan",
        )
        self.app.chat_pane.add_status(f"Executing task [{task.id}]: {task.title}...", style="bold cyan")
        prompt = build_task_prompt(task, plan.summary)
        self.app.chat_pane.add_user_message(f"Execute plan task: {task.title}")
        self.app.tool_dock.update_status(f"Task: {task.id}")
        self.app._run_agent(prompt)
        task.status = TaskStatus.COMPLETED
        await _persist_plan(self.app.agent, plan)

    async def _plan(self, args: str) -> None:
        if not args:
            self.app.chat_pane.add_status("Usage: /plan <task description>", style="bold red")
            return

        self.app.chat_pane.add_status(f"Creating plan for: {args}...")
        self.app.tool_dock.update_status("Planning...")

        try:
            from okti.agent.plan import build_plan_prompt, parse_plan_response
            from okti.models.provider import Message, Role

            codebase_context = ""
            try:
                from okti.tools.files import list_dir
                codebase_context = await list_dir(".")
            except (OSError, ValueError) as e:
                logger.debug("Codebase snapshot for plan skipped: %s", e)

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
                self.app.agent._current_plan = plan
                await _persist_plan(self.app.agent, plan)

                lines = [f"## Plan: {args}", f"\n{plan.summary}\n", "### Tasks:"]
                for task in plan.tasks:
                    status_icon = "[ ]"
                    deps = f" (depends on: {', '.join(task.dependencies)})" if task.dependencies else ""
                    lines.append(f"- {status_icon} **{task.id}**: {task.title}{deps}")
                    if task.description:
                        lines.append(f"  {task.description[:120]}")
                    if task.files_involved:
                        lines.append(f"  Files: {', '.join(task.files_involved)}")
                # Cost preview so the user knows the ballpark before approving.
                lines.append(f"\n**Estimate**: {plan.cost_summary(self.app.config.default_model)}")
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
        """Open interactive model picker popup."""
        try:
            from okti.models.factory import create_provider
            provider = create_provider(self.app.config)
            all_models = await asyncio.to_thread(provider.list_models)
            current = self.app.config.default_model
            provider_name = self.app.config.default_provider.value

            from okti.tui.model_picker import ModelPickerModal
            self.app.push_screen(
                ModelPickerModal(
                    provider_name=provider_name,
                    current_model=current,
                    models=all_models,
                ),
                callback=self._on_model_picked,
            )
        except Exception as e:
            self.app.chat_pane.add_status(f"Error opening model picker: {e}", style="bold red")

    def _on_model_picked(self, selected_model: str | None) -> None:
        """Handle model selection from modal dialog."""
        if selected_model:
            self.app.config.default_model = selected_model
            provider_name = self.app.config.default_provider.value
            if provider_name in self.app.config.providers:
                self.app.config.providers[provider_name].model = selected_model
            self.app.tool_dock.update_model(f"{provider_name} / {selected_model}")
            self.app.chat_pane.add_status(f"Active model switched to: `{selected_model}`", style="bold green")

            from okti.config import save_config_toml
            try:
                save_config_toml(self.app.config)
            except Exception as e:
                logger.warning("Failed to auto-save config.toml: %s", e)

    async def _model(self, args: str) -> None:
        """Switch active model directly and persist to config."""
        new_model = args.strip()
        if not new_model:
            self.app.chat_pane.add_status(
                f"Active model: `{self.app.config.default_model}`\nUsage: `/model <model_name>`",
                style="cyan",
            )
            return

        self.app.config.default_model = new_model
        provider_name = self.app.config.default_provider.value
        if provider_name in self.app.config.providers:
            self.app.config.providers[provider_name].model = new_model

        try:
            from okti.models.factory import create_provider
            self.app.agent.provider = create_provider(self.app.config)
        except Exception as e:
            logger.warning("Failed to rebuild provider: %s", e)

        self.app.tool_dock.update_model(f"{provider_name} / {new_model}")
        self.app.chat_pane.add_status(f"Active model switched to: `{new_model}`", style="bold green")

        from okti.config import save_config_toml
        try:
            save_config_toml(self.app.config)
        except Exception as e:
            logger.warning("Failed to auto-save config.toml: %s", e)

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

        from okti.config import ProviderID, save_config_toml
        self.app.config.default_provider = ProviderID(provider_id)

        try:
            from okti.models.factory import create_provider
            self.app.agent.provider = create_provider(self.app.config)
            self.app.tool_dock.update_model(f"Provider: {provider_id}")
            self.app.chat_pane.add_status(f"Switched to provider: {provider_id}", style="green")
            save_config_toml(self.app.config)
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
        self.app.chat_pane.add_status("Compacting context with model...")
        self.app.agent.messages = await self.app.agent.context.compact_messages(
            self.app.agent.messages,
            provider=self.app.agent.provider,
            model=self.app.config.default_model,
        )
        self.app.chat_pane.add_status("Context compacted.", style="green")

    async def _sessions(self, args: str) -> None:
        """List recent sessions."""
        try:
            from okti.storage.db import Storage
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
        """Save current session (incremental)."""
        try:
            from okti.storage.db import Storage
            storage = Storage()
            await storage.connect()

            if not self.app.agent.session_id:
                self.app.agent.session_id = await storage.create_session(
                    workspace=str(Path.cwd()),
                    model=self.app.config.default_model,
                )

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
            from okti.storage.db import Storage
            storage = Storage()
            await storage.connect()
            session = await storage.get_session(session_id)
            if not session:
                self.app.chat_pane.add_status(f"Session not found: {session_id}", style="bold red")
                await storage.close()
                return

            messages = await storage.get_messages(session_id)
            await storage.close()

            self.app.agent.session_id = session_id
            self.app.agent.messages = messages

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
        """Refresh file tree (feature stubbed pending FileTree mount in OktiApp)."""
        file_tree = getattr(self.app, "file_tree", None)
        if file_tree is None:
            self.app.chat_pane.add_status(
                "File tree not mounted in this layout.", style="yellow"
            )
            return
        try:
            file_tree.refresh_tree()
            self.app.chat_pane.add_status("File tree refreshed.", style="green")
        except (OSError, AttributeError) as e:
            self.app.chat_pane.add_status(f"Refresh error: {e}", style="bold red")

    async def _git(self, args: str) -> None:
        """Git operations."""
        from okti.tools.git_tools import (
            git_add,
            git_branch,
            git_commit,
            git_diff,
            git_log,
            git_push,
            git_remote_url,
            git_status_detailed,
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

        if subcmd == "list":
            mcp_client = self.app.agent.mcp_client
            if not mcp_client:
                self.app.chat_pane.add_assistant_message("MCP client not initialized.")
                return
            tools = mcp_client.list_tools()
            if not tools:
                self.app.chat_pane.add_assistant_message(
                    "No MCP tools connected.\n\nConfigure servers in `~/.config/okti/mcp.toml`"
                )
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

Configure MCP servers in `~/.config/okti/mcp.toml`""")
        else:
            self.app.chat_pane.add_status(f"Unknown MCP subcommand: {subcmd}. Try /mcp help", style="bold red")

    async def _plugin(self, args: str) -> None:
        """Plugin management."""
        from okti.tools.plugin import create_plugin_template, discover_plugins

        parts = args.strip().split(maxsplit=1)
        subcmd = parts[0] if parts else "list"

        if subcmd == "list":
            plugins = discover_plugins()
            if not plugins:
                self.app.chat_pane.add_assistant_message(
                    "No plugins found.\n\n"
                    "Create a plugin in `~/.config/okti/plugins/` or `.okti/plugins/`\n"
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
                f"Plugin template created at:\n`{template_path}`\n\nEdit it to add your custom tools, then restart okti."
            )
        elif subcmd == "help":
            self.app.chat_pane.add_assistant_message("""## Plugin Commands

| Command | Description |
|---------|-------------|
| `/plugin list` | List installed plugins |
| `/plugin create` | Create a plugin template |
| `/plugin help` | Show this help |

Plugins are Python files in `~/.config/okti/plugins/` or `.okti/plugins/`.""")
        else:
            self.app.chat_pane.add_status(f"Unknown plugin subcommand: {subcmd}. Try /plugin help", style="bold red")


# ---------------------------------------------------------------------------
# Plan persistence helpers
# ---------------------------------------------------------------------------

async def _persist_plan(agent, plan) -> None:
    """Save the current plan snapshot to the session's plans table.

    Silently no-ops if there is no session_id yet — the auto-save
    machinery in _auto_save() will create one on the next assistant
    turn, at which point the plan will be re-persisted.
    """
    if not agent.session_id:
        return
    from okti.storage.db import Storage
    try:
        storage = Storage()
        await storage.connect()
        await storage.save_plan(agent.session_id, plan.to_dict())
        await storage.close()
    except Exception as e:  # storage errors must not break the plan flow
        logger.warning("Plan persist failed: %s", e)


async def _plans_impl(handler) -> None:
    from okti.storage.db import Storage
    storage = Storage()
    await storage.connect()
    rows = await storage.list_plans(limit=20)
    await storage.close()
    if not rows:
        handler.app.chat_pane.add_status("No plans saved yet.", style="dim")
        return
    lines = ["## Saved plans", ""]
    for p in rows:
        n_pending = sum(1 for t in p["tasks"] if t.get("status") == "pending")
        n_total = len(p["tasks"])
        lines.append(
            f"- **{p['id']}** — {p['scope'][:60]}  ·  "
            f"{n_pending}/{n_total} pending  ·  {p['updated_at'][:19]}"
        )
    lines.append("\nType `/plan-resume` to resume the most recent plan attached to this session.")
    handler.app.chat_pane.add_assistant_message("\n".join(lines))


async def _plan_resume_impl(handler) -> None:
    from okti.agent.plan import Plan
    from okti.storage.db import Storage

    agent = handler.app.agent
    if not agent.session_id:
        handler.app.chat_pane.add_status(
            "No active session — start a plan first or /load a session.",
            style="dim",
        )
        return

    storage = Storage()
    await storage.connect()
    raw = await storage.load_plan(agent.session_id)
    await storage.close()

    if not raw:
        handler.app.chat_pane.add_status(
            "No stored plan for this session.", style="dim"
        )
        return

    plan = Plan.from_dict(raw)
    agent._current_plan = plan
    n_pending = len(plan.pending_tasks())
    n_total = len(plan.tasks)
    lines = [
        f"## Resumed plan: {plan.scope}",
        f"\n{plan.summary}\n",
        f"Status: **{n_total - n_pending}/{n_total}** tasks complete, {n_pending} pending.",
        f"Estimate for remaining work: {plan.cost_summary(handler.app.config.default_model)}",
        "",
        "Type `/approve` to continue with the next pending task.",
    ]
    handler.app.chat_pane.add_assistant_message("\n".join(lines))


# Attach the handlers to the class after definition to keep the top of
# the file readable.
async def _plans_wrapper(self, args: str) -> None:
    await _plans_impl(self)


async def _plan_resume_wrapper(self, args: str) -> None:
    await _plan_resume_impl(self)


SlashCommandHandler._plans = _plans_wrapper                  # type: ignore[attr-defined]
SlashCommandHandler._plan_resume = _plan_resume_wrapper      # type: ignore[attr-defined]


async def _budget_impl(handler, args: str) -> None:
    """/budget — show spend/cap, or set a new cap: `/budget 5.00`."""
    agent = handler.app.agent
    spent = agent.total_usage.cost_usd

    args = args.strip()
    if args:
        try:
            new_cap = float(args)
        except ValueError:
            handler.app.chat_pane.add_status(
                f"Cannot parse cap: {args!r}. Usage: /budget 5.00", style="bold red"
            )
            return
        if new_cap <= 0:
            handler.app.config.budget.session_usd_cap = None
            agent.budget.reset()
            handler.app.chat_pane.add_status("Budget cap cleared.", style="green")
        else:
            handler.app.config.budget.session_usd_cap = new_cap
            agent.budget.reset()
            handler.app.chat_pane.add_status(
                f"Budget cap set to ${new_cap:.2f} (thresholds reset).", style="green"
            )
        return

    handler.app.chat_pane.add_assistant_message(agent.budget.summary(spent))


async def _budget_wrapper(self, args: str) -> None:
    await _budget_impl(self, args)


SlashCommandHandler._budget = _budget_wrapper                # type: ignore[attr-defined]


async def _prompt_impl(handler, args: str) -> None:
    """/prompt — show which system-prompt file is active and its search chain."""
    from okti.agent.prompts import describe_prompt

    provider = handler.app.config.default_provider.value
    workspace = handler.app.config.workspace_dir
    report = describe_prompt(provider_id=provider, workspace_dir=workspace)
    handler.app.chat_pane.add_assistant_message(report)


async def _prompt_wrapper(self, args: str) -> None:
    await _prompt_impl(self, args)


SlashCommandHandler._prompt = _prompt_wrapper                # type: ignore[attr-defined]


async def _profile_impl(handler, args: str) -> None:
    """/profile — inspect or mutate the cross-session user profile."""
    from okti.context.profile import (
        _profile_path,
        forget_facts,
        load_user_profile,
    )

    args = args.strip()
    if not args:
        text = load_user_profile()
        path = _profile_path()
        if not text:
            handler.app.chat_pane.add_assistant_message(
                f"_No profile yet at `{path}`._\n\nAsk me to remember something and I will."
            )
            return
        handler.app.chat_pane.add_assistant_message(
            f"### User profile\n_Source: `{path}`_\n\n{text}"
        )
        return

    parts = args.split(maxsplit=1)
    verb = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""
    if verb in ("path", "where"):
        handler.app.chat_pane.add_assistant_message(f"Profile path: `{_profile_path()}`")
    elif verb == "forget":
        if not rest:
            handler.app.chat_pane.add_status(
                "Usage: /profile forget <substring>", style="bold red"
            )
            return
        result = forget_facts(rest)
        handler.app.chat_pane.add_status(result, style="green")
    else:
        handler.app.chat_pane.add_status(
            "Usage: /profile | /profile path | /profile forget <substring>",
            style="dim",
        )


async def _profile_wrapper(self, args: str) -> None:
    await _profile_impl(self, args)


SlashCommandHandler._profile = _profile_wrapper              # type: ignore[attr-defined]
