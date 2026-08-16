"""Onboarding wizard — interactive first-run setup for providers, models, and permissions."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, RadioButton, RadioSet, Static

from oktigent.config import (
    OktigentConfig,
    ProviderConfig,
    ProviderID,
)

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_DIR = Path.home() / ".config" / "oktigent"
_DEFAULT_CONFIG_FILE = _DEFAULT_CONFIG_DIR / "config.toml"

_DEFAULT_MODELS = {
    "ollama": "codellama",
    "anthropic": "claude-3-7-sonnet-20250219",
    "openai": "gpt-4o",
    "gemini": "gemini-2.5-flash",
    "deepseek": "deepseek-chat",
    "openrouter": "anthropic/claude-3.7-sonnet",
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
    """Check if the user is launching oktigent for the first time without configuration."""
    cfg_file = config_path or _DEFAULT_CONFIG_FILE
    if cfg_file.exists():
        return False

    # Check if any common env var is already provided
    for env_var in _ENV_KEY_MAP.values():
        if os.environ.get(env_var) or os.environ.get(f"OKTIGENT_{env_var}"):
            return False

    if os.environ.get("OLLAMA_HOST"):
        return False

    return True


def save_config_toml(config: OktigentConfig, path: Path | None = None) -> Path:
    """Serialize OktigentConfig to a clean TOML file."""
    cfg_path = path or _DEFAULT_CONFIG_FILE
    cfg_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# oktigent configuration",
        f'default_provider = "{config.default_provider.value}"',
        f'default_model = "{config.default_model}"',
        "",
        "[permissions]",
        f"yolo = {'true' if config.permissions.yolo else 'false'}",
        "",
        "[context]",
        f"max_tokens = {config.context.max_tokens}",
        f"compaction_threshold = {config.context.compaction_threshold}",
        "",
    ]

    for p_id, p_cfg in config.providers.items():
        lines.append(f"[providers.{p_id}]")
        if p_cfg.api_key:
            lines.append(f'api_key = "{p_cfg.api_key}"')
        if p_cfg.base_url:
            lines.append(f'base_url = "{p_cfg.base_url}"')
        if p_cfg.model:
            lines.append(f'model = "{p_cfg.model}"')
        lines.append(f"max_tokens = {p_cfg.max_tokens}")
        lines.append(f"temperature = {p_cfg.temperature}")
        lines.append("")

    content = "\n".join(lines).strip() + "\n"
    cfg_path.write_text(content, encoding="utf-8")
    logger.info("Saved configuration to %s", cfg_path)
    return cfg_path


class OnboardingScreen(ModalScreen[OktigentConfig | None]):
    """Interactive first-time setup wizard modal."""

    DEFAULT_CSS = """
    OnboardingScreen {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }

    #onboard-dialog {
        width: 75;
        height: auto;
        max-height: 90%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    #onboard-title {
        text-align: center;
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }

    .onboard-subtitle {
        text-style: bold;
        color: $text;
        margin-top: 1;
        margin-bottom: 0;
    }

    .onboard-hint {
        color: $text-muted;
        margin-bottom: 1;
    }

    RadioSet {
        margin-bottom: 1;
        background: transparent;
    }

    Input {
        margin-bottom: 1;
    }

    #button-bar {
        margin-top: 1;
        align: right middle;
    }

    Button {
        margin-left: 1;
    }
    """

    def __init__(self, current_config: OktigentConfig | None = None):
        super().__init__()
        self.config = current_config or OktigentConfig()
        self._selected_provider: str = self.config.default_provider.value

    def compose(self) -> ComposeResult:
        with Vertical(id="onboard-dialog"):
            yield Label("🚀 Welcome to oktigent Setup", id="onboard-title")
            yield Static(
                "Let's configure your preferred AI model provider to get started.",
                classes="onboard-hint",
            )

            with VerticalScroll():
                yield Label("1. Select Model Provider:", classes="onboard-subtitle")
                with RadioSet(id="provider-radios"):
                    yield RadioButton("Ollama (Local / Offline)", value=self._selected_provider == "ollama", id="rad-ollama")
                    yield RadioButton("Anthropic (Claude 3.7 / 3.5)", value=self._selected_provider == "anthropic", id="rad-anthropic")
                    yield RadioButton("OpenAI (GPT-4o / o3-mini)", value=self._selected_provider == "openai", id="rad-openai")
                    yield RadioButton("Google Gemini (Gemini 2.5 Flash)", value=self._selected_provider == "gemini", id="rad-gemini")
                    yield RadioButton("DeepSeek (DeepSeek-V3 / R1)", value=self._selected_provider == "deepseek", id="rad-deepseek")
                    yield RadioButton("OpenRouter (Universal gateway)", value=self._selected_provider == "openrouter", id="rad-openrouter")
                    yield RadioButton("xAI (Grok-2)", value=self._selected_provider == "xai", id="rad-xai")

                yield Label("2. Model & Credentials:", classes="onboard-subtitle")
                yield Static("Model name:", classes="onboard-hint")
                default_model = self.config.default_model or _DEFAULT_MODELS.get(self._selected_provider, "codellama")
                yield Input(value=default_model, placeholder="Model name (e.g. gpt-4o)", id="input-model")

                yield Static("API Key / Endpoint URL:", classes="onboard-hint")
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
                    placeholder="API Key (e.g. sk-...) or leave blank for Ollama",
                    password=True,
                    id="input-api-key",
                )

                yield Label("3. Execution Safety:", classes="onboard-subtitle")
                with RadioSet(id="safety-radios"):
                    yield RadioButton("Safe Mode (Ask permission before file edits / commands)", value=not self.config.permissions.yolo, id="rad-safe")
                    yield RadioButton("Yolo Mode (Auto-execute all tool calls without prompting)", value=self.config.permissions.yolo, id="rad-yolo")

                yield Static("", id="onboard-error-msg")

            with Horizontal(id="button-bar"):
                yield Button("Skip / Cancel", variant="default", id="btn-cancel")
                yield Button("Save & Start Coding", variant="primary", id="btn-save")

    @on(RadioSet.Changed, "#provider-radios")
    def on_provider_changed(self, event: RadioSet.Changed) -> None:
        """Handle provider selection change."""
        rad_id = event.pressed.id or ""
        provider = rad_id.replace("rad-", "")
        self._selected_provider = provider

        # Clear any previous validation error
        try:
            self.query_one("#onboard-error-msg", Static).update("")
        except Exception:
            pass

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
            env_val = os.environ.get(_ENV_KEY_MAP.get(provider, ""), "") or os.environ.get(f"OKTIGENT_{_ENV_KEY_MAP.get(provider, '')}", "")
            key_input.value = env_val

    @on(Button.Pressed, "#btn-cancel")
    def on_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn-save")
    def on_save(self) -> None:
        """Apply and persist selected configurations with validation."""
        model_val = self.query_one("#input-model", Input).value.strip()
        key_val = self.query_one("#input-api-key", Input).value.strip()
        is_yolo = self.query_one("#rad-yolo", RadioButton).value

        # Validate required API key for cloud providers
        if self._selected_provider != "ollama" and not key_val:
            env_name = _ENV_KEY_MAP.get(self._selected_provider, "API_KEY")
            env_val = os.environ.get(env_name, "") or os.environ.get(f"OKTIGENT_{env_name}", "")
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
                p_cfg.api_key = os.environ.get(env_name, "") or os.environ.get(f"OKTIGENT_{env_name}", "")

        p_cfg.model = self.config.default_model

        # Save to disk
        try:
            save_config_toml(self.config)
        except Exception as e:
            logger.error("Failed to save config.toml during onboarding: %s", e)

        self.dismiss(self.config)
