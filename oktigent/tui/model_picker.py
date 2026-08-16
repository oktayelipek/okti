"""Model Picker Modal Screen — Interactive searchable popup for choosing models with free-tier grouping."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

logger = logging.getLogger(__name__)

# Fallback featured spotlight models
FEATURED_MODELS = [
    "anthropic/claude-3.7-sonnet",
    "anthropic/claude-3.5-sonnet",
    "anthropic/claude-3.5-haiku",
    "openai/gpt-4o",
    "openai/o3-mini",
    "openai/gpt-4o-mini",
    "deepseek/deepseek-chat",
    "deepseek/deepseek-r1",
    "google/gemini-2.0-flash-001",
    "google/gemini-2.5-pro",
    "meta-llama/llama-3.3-70b-instruct",
    "qwen/qwen-2.5-coder-32b-instruct",
]


@dataclass
class ModelItem:
    id: str
    is_free: bool = False
    category: str = "general"


class ModelPickerModal(ModalScreen[str | None]):
    """Modern interactive modal dialog for picking AI models with free & popular grouping."""

    CSS = """
    ModelPickerModal {
        align: center middle;
        background: rgba(10, 12, 20, 0.85);
    }
    #picker-container {
        width: 85%;
        max-width: 90;
        height: 80%;
        background: #141724;
        border: round #38bdf8;
        padding: 1 2;
    }
    #picker-title {
        text-style: bold;
        color: #38bdf8;
        margin-bottom: 1;
    }
    #filter-bar {
        height: 3;
        margin-bottom: 1;
    }
    .filter-btn {
        margin-right: 1;
        min-width: 10;
        height: 1;
        background: #1e2538;
        color: #94a3b8;
    }
    .filter-btn:hover {
        background: #38bdf8;
        color: #0f111a;
    }
    .filter-btn-active {
        background: #38bdf8;
        color: #0f111a;
        text-style: bold;
    }
    #picker-search {
        border: round #6366f1;
        background: #0f111a;
        margin-bottom: 1;
    }
    #picker-options {
        height: 1fr;
        background: #0f111a;
        border: solid #1e2538;
    }
    #picker-footer {
        height: 1;
        margin-top: 1;
        color: #64748b;
        text-align: center;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "select_current", "Select"),
    ]

    def __init__(
        self,
        provider_name: str,
        current_model: str,
        models: list[str],
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.provider_name = provider_name
        self.current_model = current_model
        self.raw_models = models
        self.active_filter = "all"  # "all", "free", "featured", "claude", "gpt", "deepseek"
        self._parsed_models: list[ModelItem] = []

        for m in self.raw_models:
            is_free = ":free" in m.lower() or "free" in m.lower()
            cat = "general"
            if "claude" in m.lower() or "anthropic" in m.lower():
                cat = "claude"
            elif "gpt" in m.lower() or "openai" in m.lower() or "o3" in m.lower():
                cat = "gpt"
            elif "deepseek" in m.lower():
                cat = "deepseek"
            self._parsed_models.append(ModelItem(id=m, is_free=is_free, category=cat))

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-container"):
            yield Label(f"🤖 Select Model — Provider: [bold cyan]{self.provider_name}[/]", id="picker-title")

            with Horizontal(id="filter-bar"):
                yield Button("All", id="btn-all", classes="filter-btn filter-btn-active")
                yield Button("🆓 Free Tier", id="btn-free", classes="filter-btn")
                yield Button("⭐ Featured", id="btn-featured", classes="filter-btn")
                yield Button("Claude", id="btn-claude", classes="filter-btn")
                yield Button("GPT", id="btn-gpt", classes="filter-btn")
                yield Button("DeepSeek", id="btn-deepseek", classes="filter-btn")

            self.search_input = Input(
                placeholder="🔍 Type to search models (e.g. sonnet, r1, flash, free)...",
                id="picker-search",
            )
            yield self.search_input

            self.option_list = OptionList(id="picker-options")
            yield self.option_list

            yield Static("Use [bold cyan]↑/↓[/] to navigate · [bold cyan]Enter[/] to select · [bold cyan]Esc[/] to cancel", id="picker-footer")

    def on_mount(self) -> None:
        self._populate_options()
        self.search_input.focus()

    def _populate_options(self, search_query: str = "") -> None:
        self.option_list.clear_options()
        query = search_query.strip().lower()

        filtered: list[ModelItem] = []
        for m in self._parsed_models:
            # Check filter category
            if self.active_filter == "free" and not m.is_free:
                continue
            if self.active_filter == "featured" and m.id not in FEATURED_MODELS and not m.is_free:
                continue
            if self.active_filter == "claude" and m.category != "claude":
                continue
            if self.active_filter == "gpt" and m.category != "gpt":
                continue
            if self.active_filter == "deepseek" and m.category != "deepseek":
                continue

            # Check query search
            if query and query not in m.id.lower():
                continue

            filtered.append(m)

        # Sort: Free models first if in Free tab, or Featured first
        free_models = [m for m in filtered if m.is_free]
        paid_models = [m for m in filtered if not m.is_free]

        # Add Free models group header if any
        if free_models:
            self.option_list.add_option(Option(f"[bold green]─── 🆓 FREE TIER MODELS ({len(free_models)}) ───[/]", disabled=True))
            for m in free_models:
                is_active = m.id == self.current_model
                badge = "[bold green] FREE [/]"
                active_mark = " 🟢 [bold cyan](active)[/]" if is_active else ""
                self.option_list.add_option(Option(f"{badge}  [bold white]{m.id}[/]{active_mark}", id=m.id))

        if paid_models:
            if free_models:
                self.option_list.add_option(Option(f"[bold cyan]─── ⭐ STANDARD & PRO MODELS ({len(paid_models)}) ───[/]", disabled=True))
            for m in paid_models:
                is_active = m.id == self.current_model
                star = "⭐ " if m.id in FEATURED_MODELS else "   "
                active_mark = " 🟢 [bold cyan](active)[/]" if is_active else ""
                self.option_list.add_option(Option(f"{star} [white]{m.id}[/]{active_mark}", id=m.id))

        if not filtered:
            self.option_list.add_option(Option("[dim italic]No matching models found.[/]", disabled=True))

    @on(Input.Changed, "#picker-search")
    def on_search_changed(self, event: Input.Changed) -> None:
        self._populate_options(search_query=event.value)

    @on(Button.Pressed)
    def on_filter_btn_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if not btn_id:
            return

        for b in self.query(".filter-btn"):
            b.remove_class("filter-btn-active")
        event.button.add_class("filter-btn-active")

        if btn_id == "btn-all":
            self.active_filter = "all"
        elif btn_id == "btn-free":
            self.active_filter = "free"
        elif btn_id == "btn-featured":
            self.active_filter = "featured"
        elif btn_id == "btn-claude":
            self.active_filter = "claude"
        elif btn_id == "btn-gpt":
            self.active_filter = "gpt"
        elif btn_id == "btn-deepseek":
            self.active_filter = "deepseek"

        self._populate_options(search_query=self.search_input.value)

    @on(OptionList.OptionSelected, "#picker-options")
    def on_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_id:
            self.dismiss(event.option_id)

    def action_cancel(self) -> None:
        self.dismiss(None)
