"""Onboarding wizard — interactive first-run setup for providers, models, and permissions."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, RadioButton, RadioSet, Static

from okti.config import (
    OktiConfig,
    ProviderConfig,
    ProviderID,
    save_config_toml,
)

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_DIR = Path.home() / ".config" / "okti"
_DEFAULT_CONFIG_FILE = _DEFAULT_CONFIG_DIR / "config.toml"

_DEFAULT_MODELS = {
    "ollama": "codellama",
    "anthropic": "claude-3-7-sonnet-20250219",
    "openai": "gpt-4o",
    "gemini": "gemini-2.5-flash",
    "deepseek": "deepseek-chat",
    "openrouter": "anthropic/claude-3.5-sonnet",
    "xai": "grok-2",
}

_ENV_KEY_MAP = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "xai": "XAI_API_KEY",
}


def check_needs_onboarding(config_path: Path | None = None) -> bool:
    """Check if the user needs to run onboarding (no config or missing required API keys)."""
    cfg_file = config_path or _DEFAULT_CONFIG_FILE
    if not cfg_file.exists():
        # Check if any common env var is already provided
        for env_var in _ENV_KEY_MAP.values():
            if os.environ.get(env_var) or os.environ.get(f"OKTI_{env_var}"):
                return False

        if os.environ.get("OLLAMA_HOST"):
            return False

        return True

    # If config file exists, check if the configured provider requires an API key that is missing
    import tomllib
    try:
        with open(cfg_file, "rb") as f:
            data = tomllib.load(f)
        provider = data.get("default_provider", "ollama")
        if provider != "ollama":
            p_data = data.get("providers", {}).get(provider, {})
            key = p_data.get("api_key", "")
            env_var = _ENV_KEY_MAP.get(provider, "")
            env_key = os.environ.get(env_var, "") or os.environ.get(f"OKTI_{env_var}", "")
            if not key and not env_key:
                return True  # Configured provider has no key -> needs onboarding
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError) as e:
        logger.debug("Config parse skipped, defaulting to no onboarding: %s", e)

    return False


class OnboardingScreen(ModalScreen[OktiConfig | None]):
    """Interactive first-time setup wizard modal."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("ctrl+c", "cancel", "Cancel", show=False),
        # Enter on step 1 advances → step 2. On step 2, Ctrl+S saves.
        # (Plain Enter is left alone so it can submit Inputs / toggle radios.)
        Binding("ctrl+n", "next", "Next", show=False),
        Binding("ctrl+b", "back", "Back", show=False),
        Binding("ctrl+s", "save", "Save", show=False),
    ]

    # Crush-inspired palette — soft, clean, one accent.
    #   #16161e bg     #24243a panel   #cdd6f4 text
    #   #6c7086 muted  #cba6f7 accent  #f38ba8 error   #a6e3a1 success
    DEFAULT_CSS = """
    OnboardingScreen {
        align: center middle;
        background: rgba(16, 16, 24, 0.75);
    }

    #onboard-dialog {
        width: 68;
        height: auto;
        min-height: 30;
        max-height: 92%;
        background: #16161e;
        border: round #6c7086;
        padding: 1 3;
    }

    #onboard-title {
        text-align: center;
        text-style: bold;
        color: #cdd6f4;
        margin-bottom: 0;
    }

    #onboard-tagline {
        text-align: center;
        color: #6c7086;
        margin-bottom: 1;
    }

    #step-indicator {
        text-align: center;
        color: #cba6f7;
        text-style: bold;
        margin-bottom: 1;
    }

    .onboard-subtitle {
        text-style: bold;
        color: #cdd6f4;
        margin-top: 1;
        margin-bottom: 0;
    }

    .onboard-hint {
        color: #6c7086;
        margin-bottom: 0;
    }

    RadioSet {
        height: auto;
        min-height: 9;
        margin-bottom: 1;
        background: transparent;
        border: none;
        padding: 0;
    }

    RadioButton {
        background: transparent;
        color: #cdd6f4;
        padding: 0 1;
    }

    RadioButton.-selected {
        color: #cba6f7;
        text-style: bold;
    }

    RadioButton:hover {
        color: #cba6f7;
    }

    Input {
        margin-bottom: 1;
        background: #24243a;
        border: round #45475a;
        color: #cdd6f4;
    }

    Input:focus {
        border: round #cba6f7;
    }

    #onboard-error-msg {
        color: #f38ba8;
    }

    .step-panel.-hidden {
        display: none;
    }

    Button.-hidden {
        display: none;
    }

    #onboard-keys {
        text-align: center;
        color: #6c7086;
        margin-top: 1;
    }

    #button-bar {
        margin-top: 1;
        align: right middle;
    }

    Button {
        margin-left: 1;
        border: round #45475a;
        background: #24243a;
        color: #cdd6f4;
        min-width: 12;
    }

    Button.-primary {
        background: #cba6f7;
        border: round #cba6f7;
        color: #16161e;
        text-style: bold;
    }

    Button:hover {
        border: round #cba6f7;
        color: #cba6f7;
    }

    Button.-primary:hover {
        background: #b4a2e6;
        border: round #b4a2e6;
    }
    """

    def __init__(self, current_config: OktiConfig | None = None):
        super().__init__()
        self.config = current_config or OktiConfig()
        self._selected_provider: str = self.config.default_provider.value
        self._step: int = 1

    def compose(self) -> ComposeResult:
        with Vertical(id="onboard-dialog"):
            yield Label("okti", id="onboard-title")
            yield Static("Let's get you set up.", id="onboard-tagline")
            yield Static("Step 1 of 2  ·  Provider", id="step-indicator")

            with VerticalScroll():
                # ------- Step 1: provider selection -------
                with Vertical(id="step-1", classes="step-panel"):
                    yield Label("Choose your model provider", classes="onboard-subtitle")
                    with RadioSet(id="provider-radios"):
                        yield RadioButton("Ollama (Local / Offline)", value=self._selected_provider == "ollama", id="rad-ollama")
                        yield RadioButton("Anthropic (Claude 3.7 / 3.5)", value=self._selected_provider == "anthropic", id="rad-anthropic")
                        yield RadioButton("OpenAI (GPT-4o / o3-mini)", value=self._selected_provider == "openai", id="rad-openai")
                        yield RadioButton("Google Gemini (Gemini 2.5 Flash)", value=self._selected_provider == "gemini", id="rad-gemini")
                        yield RadioButton("DeepSeek (DeepSeek-V3 / R1)", value=self._selected_provider == "deepseek", id="rad-deepseek")
                        yield RadioButton("OpenRouter (Universal gateway)", value=self._selected_provider == "openrouter", id="rad-openrouter")
                        yield RadioButton("xAI (Grok-2)", value=self._selected_provider == "xai", id="rad-xai")

                # ------- Step 2: model + credentials + safety -------
                with Vertical(id="step-2", classes="step-panel -hidden"):
                    yield Label("Model & credentials", classes="onboard-subtitle")
                    yield Static("Model", classes="onboard-hint")
                    default_model = self.config.default_model or _DEFAULT_MODELS.get(self._selected_provider, "codellama")
                    yield Input(value=default_model, placeholder="e.g. gpt-4o", id="input-model")

                    yield Static("API key", classes="onboard-hint")
                    existing_key = ""
                    p_cfg = self.config.providers.get(self._selected_provider)
                    if p_cfg and p_cfg.api_key:
                        existing_key = p_cfg.api_key
                    else:
                        env_name = _ENV_KEY_MAP.get(self._selected_provider)
                        if env_name:
                            existing_key = os.environ.get(env_name, "")

                    yield Input(
                        value=existing_key,
                        placeholder="sk-... (leave blank for Ollama)",
                        password=True,
                        id="input-api-key",
                    )

                    yield Label("Permissions", classes="onboard-subtitle")
                    with RadioSet(id="safety-radios"):
                        yield RadioButton("Ask before file edits and commands", value=not self.config.permissions.yolo, id="rad-safe")
                        yield RadioButton("Auto-approve everything (yolo)", value=self.config.permissions.yolo, id="rad-yolo")

                yield Static("", id="onboard-error-msg")

            with Horizontal(id="button-bar"):
                yield Button("Cancel", variant="default", id="btn-cancel")
                yield Button("Back", variant="default", id="btn-back", classes="-hidden")
                yield Button("Next", variant="primary", id="btn-next")
                yield Button("Save", variant="primary", id="btn-save", classes="-hidden")

            yield Static(
                "tab · move  ↑↓ · select  space · toggle  ctrl+n next · ctrl+b back · ctrl+s save · esc cancel",
                id="onboard-keys",
            )

    @on(RadioSet.Changed, "#provider-radios")
    def on_provider_changed(self, event: RadioSet.Changed) -> None:
        """Handle provider selection change."""
        rad_id = event.pressed.id or ""
        provider = rad_id.replace("rad-", "")
        self._selected_provider = provider

        # Clear any previous validation error
        from textual.css.query import NoMatches
        try:
            self.query_one("#onboard-error-msg", Static).update("")
        except NoMatches:
            pass  # error widget not mounted yet — fine

        # Update model input placeholder and default value
        model_input = self.query_one("#input-model", Input)
        default_model = _DEFAULT_MODELS.get(provider, "")
        model_input.value = default_model

        # Update API key input with environment key if present
        key_input = self.query_one("#input-api-key", Input)
        if provider == "ollama":
            key_input.placeholder = "Ollama Base URL (default: http://localhost:11434)"
            key_input.password = False
            key_input.value = "http://localhost:11434"
        else:
            key_input.placeholder = f"API Key for {provider.capitalize()} (required)"
            key_input.password = True
            env_val = os.environ.get(_ENV_KEY_MAP.get(provider, ""), "") or os.environ.get(f"OKTI_{_ENV_KEY_MAP.get(provider, '')}", "")
            key_input.value = env_val

    def on_mount(self) -> None:
        """Auto-focus the provider list so arrow keys work immediately."""
        try:
            self.query_one("#provider-radios", RadioSet).focus()
        except Exception:
            pass

    def _show_step(self, step: int) -> None:
        """Toggle visible step panel and button set."""
        self._step = step
        self.query_one("#step-1").set_class(step != 1, "-hidden")
        self.query_one("#step-2").set_class(step != 2, "-hidden")
        self.query_one("#btn-next", Button).set_class(step != 1, "-hidden")
        self.query_one("#btn-back", Button).set_class(step != 2, "-hidden")
        self.query_one("#btn-save", Button).set_class(step != 2, "-hidden")
        indicator = self.query_one("#step-indicator", Static)
        if step == 1:
            indicator.update("Step 1 of 2  ·  Provider")
        else:
            indicator.update("Step 2 of 2  ·  Credentials")
        # Move focus to the primary input on the visible step for keyboard flow
        if step == 2:
            try:
                self.query_one("#input-api-key", Input).focus()
            except Exception:
                pass

    @on(Button.Pressed, "#btn-next")
    def on_next(self) -> None:
        self._show_step(2)

    @on(Button.Pressed, "#btn-back")
    def on_back(self) -> None:
        self._show_step(1)

    @on(Button.Pressed, "#btn-cancel")
    def on_cancel(self) -> None:
        self.dismiss(None)

    # Keyboard-only equivalents of the button bar. Wired via BINDINGS above.
    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_next(self) -> None:
        if self._step == 1:
            self._show_step(2)

    def action_back(self) -> None:
        if self._step == 2:
            self._show_step(1)

    def action_save(self) -> None:
        if self._step == 2:
            self.on_save()

    @on(Button.Pressed, "#btn-save")
    def on_save(self) -> None:
        """Apply and persist selected configurations with validation."""
        model_val = self.query_one("#input-model", Input).value.strip()
        key_val = self.query_one("#input-api-key", Input).value.strip()
        is_yolo = self.query_one("#rad-yolo", RadioButton).value

        # Validate required API key for cloud providers
        if self._selected_provider != "ollama" and not key_val:
            env_name = _ENV_KEY_MAP.get(self._selected_provider, "API_KEY")
            env_val = os.environ.get(env_name, "") or os.environ.get(f"OKTI_{env_name}", "")
            if not env_val:
                error_static = self.query_one("#onboard-error-msg", Static)
                error_static.update(
                    f"[bold red]⚠️ API Key is required for {self._selected_provider.capitalize()}![/bold red]\n"
                    f"[yellow]Please enter your key above or set the {env_name} environment variable.[/yellow]"
                )
                self.query_one("#input-api-key", Input).focus()
                return

        # Build updated config
        provider_id = ProviderID(self._selected_provider)
        self.config.default_provider = provider_id
        self.config.default_model = model_val or _DEFAULT_MODELS.get(self._selected_provider, "codellama")
        self.config.permissions.yolo = is_yolo

        if self._selected_provider not in self.config.providers:
            self.config.providers[self._selected_provider] = ProviderConfig()

        p_cfg = self.config.providers[self._selected_provider]
        if self._selected_provider == "ollama":
            if key_val and key_val.startswith("http"):
                p_cfg.base_url = key_val
            elif not p_cfg.base_url:
                p_cfg.base_url = "http://localhost:11434"
        else:
            if key_val:
                p_cfg.api_key = key_val
            elif not p_cfg.api_key:
                env_name = _ENV_KEY_MAP.get(self._selected_provider, "")
                p_cfg.api_key = os.environ.get(env_name, "") or os.environ.get(f"OKTI_{env_name}", "")

        p_cfg.model = self.config.default_model

        # Save to disk
        try:
            save_config_toml(self.config)
        except Exception as e:
            logger.error("Failed to save config.toml during onboarding: %s", e)

        self.dismiss(self.config)
