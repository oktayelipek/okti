"""Configuration — Pydantic settings + TOML file + env vars."""

from __future__ import annotations

import logging
import tomllib
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PermissionLevel(str, Enum):
    """Tool permission levels."""

    ALLOW = "allow"   # execute without asking
    ASK = "ask"       # ask the user before executing (default)
    DENY = "deny"     # refuse to execute


class ProviderID(str, Enum):
    """Supported provider identifiers."""

    OLLAMA = "ollama"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    DEEPSEEK = "deepseek"
    OPENROUTER = "openrouter"
    XAI = "xai"


# ---------------------------------------------------------------------------
# Sub-configs
# ---------------------------------------------------------------------------


class ProviderConfig(BaseModel):
    """Per-provider settings."""

    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    max_tokens: int = 8192
    temperature: float = 0.0
    extra_headers: dict[str, str] = Field(default_factory=dict)


class PermissionRule(BaseModel):
    """Single tool permission rule."""

    tool: str
    level: PermissionLevel = PermissionLevel.ASK


class PermissionsConfig(BaseModel):
    """Permission configuration."""

    yolo: bool = False
    rules: list[PermissionRule] = Field(default_factory=list)

    def get_level(self, tool_name: str) -> PermissionLevel:
        """Get permission level for a tool. Yolo overrides everything."""
        if self.yolo:
            return PermissionLevel.ALLOW
        for rule in self.rules:
            if rule.tool == tool_name:
                return rule.level
        return PermissionLevel.ASK


class ContextConfig(BaseModel):
    """Context management settings."""

    max_tokens: int = 128_000
    compaction_threshold: float = 0.75  # compact when 75% full
    background_max_chars: int = 50_000  # max chars for background context


class BudgetConfig(BaseModel):
    """Session-scoped USD spending cap.

    session_usd_cap  — None disables the cap. When set, okti tracks
                       cumulative cost across the session and takes
                       progressively louder action as it approaches
                       the cap.
    warn_at          — fraction (0-1) at which a warning is shown.
    disable_yolo_at  — fraction at which YOLO is forcibly turned off
                       so a runaway agent has to ask for permission.
    hard_stop_at     — fraction at which further tool calls are refused
                       ("budget exceeded"). Set >1 to disable the stop.
    """

    session_usd_cap: float | None = None
    warn_at: float = 0.8
    disable_yolo_at: float = 0.9
    hard_stop_at: float = 1.0


class TelemetryConfig(BaseModel):
    """Tracing / observability settings."""

    enabled: bool = False
    export_path: Path | None = None  # defaults to $OKTI_WORKSPACE/.okti/traces.jsonl
    # OTLP exporter — only used when opentelemetry-sdk is installed.
    otlp_endpoint: str | None = None  # e.g. "http://localhost:4317"; falls back to OTEL_EXPORTER_OTLP_ENDPOINT
    service_name: str = "okti"


class PluginsConfig(BaseModel):
    """Plugin loading & trust settings.

    Plugins execute arbitrary Python code with the process' privileges.
    They are disabled by default and require explicit hash-based trust.
    """

    enabled: bool = False
    trusted_hashes: list[str] = Field(default_factory=list)
    allow_untrusted: bool = False  # override for CI/dev; DO NOT use in prod


class OktiConfig(BaseModel):
    """Top-level configuration."""

    # Provider
    default_provider: ProviderID = ProviderID.OLLAMA
    default_model: str = "codellama"
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)

    # Permissions
    permissions: PermissionsConfig = Field(default_factory=PermissionsConfig)

    # Context
    context: ContextConfig = Field(default_factory=ContextConfig)

    # Paths
    workspace_dir: Path | None = None
    sessions_dir: Path | None = None

    # TUI
    theme: str = "monokai"
    show_token_usage: bool = True
    show_sidebar: bool = False  # FileTree sidebar; toggle at runtime with Ctrl+B

    # Sessions
    auto_save: bool = True  # auto-save after each assistant turn

    # Plugins
    plugins: PluginsConfig = Field(default_factory=PluginsConfig)

    # Telemetry (in-repo JSONL exporter by default; OTel auto-detected)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)

    # Budget (session USD cap with tiered enforcement)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG_DIR = Path.home() / ".config" / "okti"
_DEFAULT_CONFIG_FILE = _DEFAULT_CONFIG_DIR / "config.toml"


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep-merge override into base dict."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_toml(path: Path) -> dict[str, Any]:
    """Load a TOML config file."""
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        data = tomllib.load(f)
    logger.debug("Loaded config from %s", path)
    return data


def load_config(config_path: Path | None = None) -> OktiConfig:
    """Load configuration from TOML file, env vars, and defaults."""
    # 1. Try explicit path
    if config_path and config_path.exists():
        raw = _load_toml(config_path)
    # 2. Try default location
    elif _DEFAULT_CONFIG_FILE.exists():
        raw = _load_toml(_DEFAULT_CONFIG_FILE)
    else:
        raw = {}

    # 3. Build config
    try:
        config = OktiConfig(**raw)
    except Exception as e:
        logger.warning("Config parse error, using defaults: %s", e)
        config = OktiConfig()

    # 4. Env var overrides (OKTI_*)
    _apply_env_overrides(config)

    return config


def _apply_env_overrides(config: OktiConfig) -> None:
    """Apply environment variable overrides."""
    import os

    # API keys
    env_key_map = {
        "OKTI_OPENAI_API_KEY": ("openai", "api_key"),
        "OKTI_ANTHROPIC_API_KEY": ("anthropic", "api_key"),
        "OKTI_GEMINI_API_KEY": ("gemini", "api_key"),
        "OKTI_DEEPSEEK_API_KEY": ("deepseek", "api_key"),
        "OKTI_OPENROUTER_API_KEY": ("openrouter", "api_key"),
        "OKTI_XAI_API_KEY": ("xai", "api_key"),
        "OPENAI_API_KEY": ("openai", "api_key"),
        "ANTHROPIC_API_KEY": ("anthropic", "api_key"),
        "GOOGLE_API_KEY": ("gemini", "api_key"),
        "DEEPSEEK_API_KEY": ("deepseek", "api_key"),
        "OPENROUTER_API_KEY": ("openrouter", "api_key"),
        "XAI_API_KEY": ("xai", "api_key"),
        "OLLAMA_HOST": ("ollama", "base_url"),
    }

    for env_var, (provider, field) in env_key_map.items():
        value = os.environ.get(env_var)
        if value:
            if provider not in config.providers:
                config.providers[provider] = ProviderConfig()
            setattr(config.providers[provider], field, value)

    # Default model
    default_model = os.environ.get("OKTI_MODEL")
    if default_model:
        config.default_model = default_model

    # Yolo mode
    if os.environ.get("OKTI_YOLO", "").lower() in ("1", "true", "yes"):
        config.permissions.yolo = True


def save_config_toml(config: OktiConfig, path: Path | None = None) -> Path:
    """Serialize OktiConfig to a clean TOML file."""
    cfg_path = path or _DEFAULT_CONFIG_FILE
    cfg_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# okti configuration",
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
