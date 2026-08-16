"""OpenAI-compatible provider — works with OpenAI, DeepSeek, OpenRouter, xAI, etc."""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

import httpx

from oktigent.models.provider import (
    BaseProvider,
    Message,
    ProviderResponse,
    Role,
    StreamChunk,
    ToolCall,
    TokenUsage,
)

logger = logging.getLogger(__name__)

# Base URLs for various OpenAI-compatible providers
_PROVIDER_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "xai": "https://api.x.ai/v1",
}


class OpenAICompatProvider(BaseProvider):
    """OpenAI-compatible chat completions API provider."""

    provider_id = "openai"

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        provider_name: str = "openai",
    ):
        self.api_key = api_key
        self.base_url = (base_url or _PROVIDER_URLS.get(provider_name, _PROVIDER_URLS["openai"])).rstrip("/")
        self.provider_name = provider_name

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        # OpenRouter needs extra headers
        if self.provider_name == "openrouter":
            headers["HTTP-Referer"] = "https://github.com/oktigent/oktigent"
            headers["X-Title"] = "oktigent"
        return headers

    async def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> ProviderResponse:
        payload = self._build_payload(messages, tools, model, max_tokens, temperature, stream=False)
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=self._headers(),
            )
            if resp.status_code >= 400:
                try:
                    err_json = resp.json()
                    err_msg = err_json.get("error", {}).get("message") or err_json.get("message") or resp.text
                except Exception:
                    err_msg = resp.text
                raise RuntimeError(f"[{self.provider_name.capitalize()} API Error {resp.status_code}]: {err_msg}")
            data = resp.json()

        choice = data["choices"][0]
        msg = choice["message"]
        usage = TokenUsage(
            prompt_tokens=data.get("usage", {}).get("prompt_tokens", 0),
            completion_tokens=data.get("usage", {}).get("completion_tokens", 0),
            total_tokens=data.get("usage", {}).get("total_tokens", 0),
        )

        tool_calls = [ToolCall.from_raw(tc) for tc in msg.get("tool_calls", [])]

        message = Message(
            role=Role.ASSISTANT,
            content=msg.get("content", ""),
            tool_calls=tool_calls,
            model=data.get("model", model or ""),
        )
        return ProviderResponse(message=message, usage=usage, model=data.get("model", ""))

    async def stream_chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[StreamChunk]:
        payload = self._build_payload(messages, tools, model, max_tokens, temperature, stream=True)
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=self._headers(),
            ) as resp:
                if resp.status_code >= 400:
                    raw = await resp.aread()
                    try:
                        err_json = json.loads(raw.decode())
                        err_msg = err_json.get("error", {}).get("message") or err_json.get("message") or raw.decode()
                    except Exception:
                        err_msg = raw.decode()
                    raise RuntimeError(f"[{self.provider_name.capitalize()} API Error {resp.status_code}]: {err_msg}")
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        yield StreamChunk(finish_reason="stop")
                        return
                    data = json.loads(data_str)
                    choice = data.get("choices", [{}])[0]
                    delta = choice.get("delta", {})
                    finish = choice.get("finish_reason")

                    content = delta.get("content", "")
                    if content:
                        yield StreamChunk(content_delta=content)

                    for tc_delta in delta.get("tool_calls", []):
                        func = tc_delta.get("function", {})
                        # OpenAI sends arguments as incremental JSON string
                        args_str = func.get("arguments", "")
                        args = {"_raw": args_str} if args_str else {}
                        yield StreamChunk(
                            tool_call_delta=ToolCall(
                                id=tc_delta.get("id", ""),
                                name=func.get("name", ""),
                                arguments=args,
                            )
                        )

                    if finish:
                        usage_data = data.get("usage", {})
                        yield StreamChunk(
                            finish_reason=finish,
                            token_usage=TokenUsage(
                                prompt_tokens=usage_data.get("prompt_tokens", 0),
                                completion_tokens=usage_data.get("completion_tokens", 0),
                                total_tokens=usage_data.get("total_tokens", 0),
                            ),
                        )

    def list_models(self) -> list[str]:
        """Fetch models from the provider's /models endpoint."""
        try:
            import httpx as _httpx
            with _httpx.Client(timeout=15) as client:
                resp = client.get(f"{self.base_url}/models", headers=self._headers())
                if resp.status_code >= 400:
                    logger.warning("Failed to fetch models from %s: %s", self.base_url, resp.text)
                    return [self._default_model()]
                data = resp.json()
                models = [m["id"] for m in data.get("data", []) if "id" in m]
                return sorted(models) if models else [self._default_model()]
        except Exception as e:
            logger.warning("Error fetching models: %s", e)
            return [self._default_model()]

    def _default_model(self) -> str:
        defaults = {
            "openai": "gpt-4o",
            "deepseek": "deepseek-chat",
            "openrouter": "anthropic/claude-3.7-sonnet",
            "xai": "grok-2",
        }
        return defaults.get(self.provider_name, "gpt-4o")

    def _build_payload(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        max_tokens: int | None,
        temperature: float | None,
        stream: bool = True,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model or self._default_model(),
            "messages": [m.to_dict() for m in messages],
            "stream": stream,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if temperature is not None:
            payload["temperature"] = temperature
        return payload
