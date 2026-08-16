"""Provider factory — creates the right provider based on config.

Supports: Ollama, OpenAI, DeepSeek, OpenRouter, xAI, Anthropic, Gemini.
"""

from __future__ import annotations

import logging

from oktigent.config import OktigentConfig
from oktigent.models.provider import BaseProvider

logger = logging.getLogger(__name__)


def create_provider(
    config: OktigentConfig,
    provider_override: str | None = None,
) -> BaseProvider:
    """Create a provider instance based on config.

    Args:
        config: Full oktigent configuration
        provider_override: Override provider (e.g., "ollama", "openai", "anthropic")
    """
    provider_id = provider_override or config.default_provider.value

    # Check if it's a compound string like "ollama/codellama"
    if "/" in provider_id:
        provider_id, model_override = provider_id.split("/", 1)
        config.default_model = model_override

    provider_config = config.providers.get(provider_id)

    if provider_id == "ollama":
        from oktigent.models.ollama import OllamaProvider
        base_url = provider_config.base_url if provider_config else None
        return OllamaProvider(base_url=base_url or "http://localhost:11434")

    elif provider_id == "openai":
        from oktigent.models.openai_compat import OpenAICompatProvider
        api_key = provider_config.api_key if provider_config else None
        if not api_key:
            raise ValueError("OpenAI API key required. Set OKTIGENT_OPENAI_API_KEY or OPENAI_API_KEY env var.")
        return OpenAICompatProvider(api_key=api_key, provider_name="openai")

    elif provider_id == "deepseek":
        from oktigent.models.openai_compat import OpenAICompatProvider
        api_key = provider_config.api_key if provider_config else None
        if not api_key:
            raise ValueError("DeepSeek API key required. Set OKTIGENT_DEEPSEEK_API_KEY env var.")
        return OpenAICompatProvider(api_key=api_key, provider_name="deepseek")

    elif provider_id == "openrouter":
        from oktigent.models.openai_compat import OpenAICompatProvider
        api_key = provider_config.api_key if provider_config else None
        if not api_key:
            raise ValueError("OpenRouter API key required. Set OKTIGENT_OPENROUTER_API_KEY env var.")
        return OpenAICompatProvider(api_key=api_key, provider_name="openrouter")

    elif provider_id == "xai":
        from oktigent.models.openai_compat import OpenAICompatProvider
        api_key = provider_config.api_key if provider_config else None
        if not api_key:
            raise ValueError("xAI API key required. Set OKTIGENT_XAI_API_KEY env var.")
        return OpenAICompatProvider(api_key=api_key, provider_name="xai")

    elif provider_id == "anthropic":
        from oktigent.models.anthropic import AnthropicProvider
        api_key = provider_config.api_key if provider_config else None
        if not api_key:
            raise ValueError("Anthropic API key required. Set OKTIGENT_ANTHROPIC_API_KEY or ANTHROPIC_API_KEY env var.")
        base_url = provider_config.base_url if provider_config else None
        return AnthropicProvider(api_key=api_key, base_url=base_url or "https://api.anthropic.com")

    elif provider_id == "gemini":
        from oktigent.models.gemini import GeminiProvider
        api_key = provider_config.api_key if provider_config else None
        if not api_key:
            raise ValueError("Gemini API key required. Set OKTIGENT_GEMINI_API_KEY or GOOGLE_API_KEY env var.")
        return GeminiProvider(api_key=api_key)

    else:
        # Try as OpenAI-compatible (generic fallback)
        from oktigent.models.openai_compat import OpenAICompatProvider
        if provider_config and provider_config.api_key and provider_config.base_url:
            return OpenAICompatProvider(
                api_key=provider_config.api_key,
                base_url=provider_config.base_url,
                provider_name=provider_id,
            )
        raise ValueError(f"Unknown provider: {provider_id}. Set a base_url and api_key in config.")
