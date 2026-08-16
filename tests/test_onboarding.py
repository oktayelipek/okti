"""Tests for onboarding wizard, config saving, and setup flow."""

import os
import tomllib
from oktigent.config import OktigentConfig, ProviderConfig, ProviderID
from oktigent.models.factory import create_provider
from oktigent.tui.onboarding import check_needs_onboarding, save_config_toml, OnboardingScreen


def test_save_config_toml(tmp_path):
    config = OktigentConfig()
    config.default_provider = ProviderID.ANTHROPIC
    config.default_model = "claude-3-7-sonnet-20250219"
    config.permissions.yolo = True
    config.providers["anthropic"] = ProviderConfig(
        api_key="sk-ant-testkey123",
        model="claude-3-7-sonnet-20250219",
    )

    out_file = tmp_path / "config.toml"
    save_config_toml(config, out_file)

    assert out_file.exists()
    with open(out_file, "rb") as f:
        data = tomllib.load(f)

    assert data["default_provider"] == "anthropic"
    assert data["default_model"] == "claude-3-7-sonnet-20250219"
    assert data["permissions"]["yolo"] is True
    assert data["providers"]["anthropic"]["api_key"] == "sk-ant-testkey123"


def test_check_needs_onboarding_with_existing_file(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('default_provider = "ollama"\n', encoding="utf-8")

    assert check_needs_onboarding(cfg_file) is False


def test_check_needs_onboarding_no_file(tmp_path):
    non_existent = tmp_path / "does_not_exist.toml"
    # Ensure env vars aren't set during this test
    orig_env = os.environ.copy()
    for k in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "DEEPSEEK_API_KEY", "OLLAMA_HOST"]:
        os.environ.pop(k, None)
        os.environ.pop(f"OKTIGENT_{k}", None)

    try:
        assert check_needs_onboarding(non_existent) is True
    finally:
        os.environ.clear()
        os.environ.update(orig_env)


def test_onboarding_screen_instantiation():
    config = OktigentConfig()
    screen = OnboardingScreen(config)
    assert screen.config == config
    assert screen._selected_provider == "ollama"


def test_create_provider_openrouter_with_config_key():
    config = OktigentConfig()
    config.default_provider = ProviderID.OPENROUTER
    config.providers["openrouter"] = ProviderConfig(api_key="sk-or-test-key-123")
    provider = create_provider(config)
    assert provider.provider_name == "openrouter"
    assert provider.api_key == "sk-or-test-key-123"
