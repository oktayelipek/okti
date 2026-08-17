"""Ollama provider — local models via Ollama's OpenAI-compatible API."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from okti.models.provider import (
    BaseProvider,
    Message,
    ProviderResponse,
    Role,
    StreamChunk,
    TokenUsage,
    ToolCall,
)

logger = logging.getLogger(__name__)


class OllamaProvider(BaseProvider):
    """Ollama provider using OpenAI-compatible /v1/chat/completions."""

    provider_id = "ollama"

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        api_key: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key  # Ollama doesn't need one, but keeps interface

    async def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> ProviderResponse:
        payload = self._build_payload(messages, tools, model, max_tokens, temperature, stream=False)
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(f"{self.base_url}/v1/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()

        choice = data["choices"][0]
        msg = choice["message"]
        usage = TokenUsage(
            prompt_tokens=data.get("usage", {}).get("prompt_tokens", 0),
            completion_tokens=data.get("usage", {}).get("completion_tokens", 0),
            total_tokens=data.get("usage", {}).get("total_tokens", 0),
        )

        tool_calls = []
        for tc in msg.get("tool_calls", []):
            tool_calls.append(ToolCall.from_raw(tc))

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
        async with httpx.AsyncClient(timeout=300) as client, client.stream(
            "POST",
            f"{self.base_url}/v1/chat/completions",
            json=payload,
        ) as resp:
            resp.raise_for_status()
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

                # Tool call streaming (accumulated)
                for tc_delta in delta.get("tool_calls", []):
                    func = tc_delta.get("function", {})
                    # Ollama may send arguments as string or dict
                    args = func.get("arguments", {})
                    if isinstance(args, str):
                        args = {"_raw": args}
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
        """Fetch available models from Ollama."""
        try:
            import httpx as _httpx
            with _httpx.Client(timeout=5) as client:
                resp = client.get(f"{self.base_url}/api/tags")
                resp.raise_for_status()
                data = resp.json()
                return [m["name"] for m in data.get("models", [])]
        except Exception:
            return ["codellama", "llama3", "deepseek-coder", "qwen2.5-coder"]

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
            "model": model or "codellama",
            "messages": [m.to_dict() for m in messages],
            "stream": stream,
        }
        if tools:
            payload["tools"] = tools
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if temperature is not None:
            payload["temperature"] = temperature
        return payload
