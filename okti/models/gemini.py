"""Google Gemini provider — using Google AI Generative Language API."""

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


class GeminiProvider(BaseProvider):
    """Google Gemini provider using the Generative Language API."""

    provider_id = "gemini"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://generativelanguage.googleapis.com",
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def _convert_messages(
        self, messages: list[Message]
    ) -> tuple[str, list[dict[str, Any]]]:
        """Convert to Gemini contents format."""
        system = ""
        contents: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == Role.SYSTEM:
                system = msg.content
                continue

            role = "model" if msg.role == Role.ASSISTANT else "user"
            parts: list[dict[str, Any]] = []

            if msg.content:
                parts.append({"text": msg.content})

            for tc in msg.tool_calls:
                parts.append({
                    "functionCall": {
                        "name": tc.name,
                        "args": tc.arguments,
                    }
                })

            if msg.role == Role.TOOL:
                contents.append({
                    "role": "user",
                    "parts": [{
                        "functionResponse": {
                            "name": msg.name or msg.tool_call_id or "unknown",
                            "response": {"result": msg.content},
                        }
                    }],
                })
                continue

            contents.append({"role": role, "parts": parts})

        return system, contents

    def _convert_tools(self, tools: list[dict[str, Any]]) -> dict[str, Any]:
        """Convert tools to Gemini function_declarations format."""
        func_decls = []
        for t in tools:
            func = t.get("function", t)
            func_decls.append({
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "parameters": func.get("parameters", {"type": "object", "properties": {}}),
            })
        return {"function_declarations": func_decls}

    def _model_name(self, model: str | None) -> str:
        return model or "gemini-2.5-flash"

    async def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> ProviderResponse:
        system, contents = self._convert_messages(messages)
        model_name = self._model_name(model)

        payload: dict[str, Any] = {
            "contents": contents,
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            payload["tools"] = self._convert_tools(tools)
        config: dict[str, Any] = {}
        if max_tokens is not None:
            config["maxOutputTokens"] = max_tokens
        if temperature is not None:
            config["temperature"] = temperature
        if config:
            payload["generationConfig"] = config

        url = f"{self.base_url}/v1beta/models/{model_name}:generateContent"
        headers = {"x-goog-api-key": self.api_key}
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        candidate = data.get("candidates", [{}])[0]
        content_parts = candidate.get("content", {}).get("parts", [])

        text = ""
        tool_calls: list[ToolCall] = []
        for part in content_parts:
            if "text" in part:
                text += part["text"]
            if "functionCall" in part:
                fc = part["functionCall"]
                tool_calls.append(ToolCall(
                    id=f"gemini_{len(tool_calls)}",
                    name=fc["name"],
                    arguments=fc.get("args", {}),
                ))

        usage_data = data.get("usageMetadata", {})
        usage = TokenUsage(
            prompt_tokens=usage_data.get("promptTokenCount", 0),
            completion_tokens=usage_data.get("candidatesTokenCount", 0),
            total_tokens=usage_data.get("totalTokenCount", 0),
        )

        message = Message(
            role=Role.ASSISTANT,
            content=text,
            tool_calls=tool_calls,
            model=model_name,
        )
        return ProviderResponse(message=message, usage=usage, model=model_name)

    async def stream_chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[StreamChunk]:
        system, contents = self._convert_messages(messages)
        model_name = self._model_name(model)

        payload: dict[str, Any] = {
            "contents": contents,
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            payload["tools"] = self._convert_tools(tools)
        config: dict[str, Any] = {}
        if max_tokens is not None:
            config["maxOutputTokens"] = max_tokens
        if temperature is not None:
            config["temperature"] = temperature
        if config:
            payload["generationConfig"] = config

        url = f"{self.base_url}/v1beta/models/{model_name}:streamGenerateContent?alt=sse"
        headers = {"x-goog-api-key": self.api_key}
        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data = json.loads(line[6:])
                    candidate = data.get("candidates", [{}])[0]
                    parts = candidate.get("content", {}).get("parts", [])
                    for part in parts:
                        if "text" in part:
                            yield StreamChunk(content_delta=part["text"])
                        if "functionCall" in part:
                            fc = part["functionCall"]
                            yield StreamChunk(
                                tool_call_delta=ToolCall(
                                    id=f"gemini_{len(fc)}",
                                    name=fc["name"],
                                    arguments=fc.get("args", {}),
                                )
                            )
                    finish = candidate.get("finishReason")
                    if finish:
                        usage_data = data.get("usageMetadata", {})
                        yield StreamChunk(
                            finish_reason=finish,
                            token_usage=TokenUsage(
                                prompt_tokens=usage_data.get("promptTokenCount", 0),
                                completion_tokens=usage_data.get("candidatesTokenCount", 0),
                                total_tokens=usage_data.get("totalTokenCount", 0),
                            ),
                        )

    def list_models(self) -> list[str]:
        return [
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
        ]
