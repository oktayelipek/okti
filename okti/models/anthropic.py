"""Anthropic Claude provider — native Anthropic Messages API with tool use."""

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


class AnthropicProvider(BaseProvider):
    """Anthropic Claude provider using the native Messages API."""

    provider_id = "anthropic"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.anthropic.com",
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    def _convert_messages(
        self, messages: list[Message]
    ) -> tuple[str, list[dict[str, Any]]]:
        """Extract system prompt and convert messages to Anthropic format.

        Anthropic requires system as a separate parameter, not in messages.
        """
        system = ""
        converted: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == Role.SYSTEM:
                system = msg.content
                continue
            if msg.role == Role.TOOL:
                converted.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg.tool_call_id,
                            "content": msg.content,
                        }
                    ],
                })
                continue

            # User or Assistant
            content: list[dict[str, Any]] = []
            if msg.content:
                content.append({"type": "text", "text": msg.content})

            for tc in msg.tool_calls:
                content.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.arguments,
                })

            converted.append({
                "role": msg.role.value,
                "content": content if content else msg.content or [],
            })

        return system, converted

    def _convert_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert tools to Anthropic format."""
        result = []
        for t in tools:
            func = t.get("function", t)
            result.append({
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
            })
        return result

    async def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> ProviderResponse:
        from okti.models.retry import retry_with_backoff

        system, converted = self._convert_messages(messages)
        payload: dict[str, Any] = {
            "model": model or "claude-sonnet-4-20250514",
            "messages": converted,
            "max_tokens": max_tokens or 8192,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = self._convert_tools(tools)
        if temperature is not None:
            payload["temperature"] = temperature

        async def _call():
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"{self.base_url}/v1/messages",
                    json=payload,
                    headers=self._headers(),
                )
                resp.raise_for_status()
                return resp.json()

        data = await retry_with_backoff(_call)

        # Parse response
        content_text = ""
        tool_calls: list[ToolCall] = []
        for block in data.get("content", []):
            if block["type"] == "text":
                content_text += block["text"]
            elif block["type"] == "tool_use":
                tool_calls.append(
                    ToolCall(id=block["id"], name=block["name"], arguments=block["input"])
                )

        usage_data = data.get("usage", {})
        usage = TokenUsage(
            prompt_tokens=usage_data.get("input_tokens", 0),
            completion_tokens=usage_data.get("output_tokens", 0),
            total_tokens=usage_data.get("input_tokens", 0) + usage_data.get("output_tokens", 0),
        )

        message = Message(
            role=Role.ASSISTANT,
            content=content_text,
            tool_calls=tool_calls,
            model=data.get("model", ""),
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
        system, converted = self._convert_messages(messages)
        payload: dict[str, Any] = {
            "model": model or "claude-sonnet-4-20250514",
            "messages": converted,
            "max_tokens": max_tokens or 8192,
            "stream": True,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = self._convert_tools(tools)
        if temperature is not None:
            payload["temperature"] = temperature

        current_tool_id = ""
        current_tool_name = ""
        current_tool_args = ""
        tool_index = 0

        max_retries = 3
        for attempt in range(max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=300) as client:
                    async with client.stream(
                        "POST",
                        f"{self.base_url}/v1/messages",
                        json=payload,
                        headers=self._headers(),
                    ) as resp:
                        if resp.status_code >= 400:
                            raw = await resp.aread()
                            err_text = raw.decode()
                            if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                                import asyncio as _aio
                                delay = 2 ** attempt
                                retry_after = resp.headers.get("retry-after", "")
                                try:
                                    delay = max(delay, float(retry_after))
                                except (ValueError, TypeError):
                                    pass
                                logger.warning("Anthropic HTTP %d (attempt %d/%d), retrying in %.1fs",
                                    resp.status_code, attempt + 1, max_retries + 1, delay)
                                await _aio.sleep(delay)
                                continue
                            raise RuntimeError(f"[Anthropic API Error {resp.status_code}]: {err_text}")

                        async for line in resp.aiter_lines():
                            if not line or not line.startswith("data: "):
                                continue
                            data = json.loads(line[6:])
                            event_type = data.get("type", "")

                            if event_type == "content_block_start":
                                block = data.get("content_block", {})
                                if block.get("type") == "tool_use":
                                    current_tool_id = block.get("id", "")
                                    current_tool_name = block.get("name", "")
                                    current_tool_args = ""
                            elif event_type == "content_block_delta":
                                delta = data.get("delta", {})
                                if delta.get("type") == "text_delta":
                                    yield StreamChunk(content_delta=delta.get("text", ""))
                                elif delta.get("type") == "input_json_delta":
                                    current_tool_args += delta.get("partial_json", "")
                            elif event_type == "content_block_stop":
                                if current_tool_name:
                                    try:
                                        args = json.loads(current_tool_args) if current_tool_args else {}
                                    except json.JSONDecodeError:
                                        args = {"_raw": current_tool_args}
                                    yield StreamChunk(
                                        tool_call_delta=ToolCall(
                                            id=current_tool_id,
                                            name=current_tool_name,
                                            arguments=args,
                                        )
                                    )
                                    current_tool_name = ""
                                    current_tool_id = ""
                                    tool_index += 1
                            elif event_type == "message_delta":
                                stop = data.get("delta", {}).get("stop_reason")
                                if stop:
                                    usage_data = data.get("usage", {})
                                    yield StreamChunk(
                                        finish_reason=stop,
                                        token_usage=TokenUsage(
                                            completion_tokens=usage_data.get("output_tokens", 0),
                                        ),
                                    )
                        return  # Stream completed

            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as e:
                if attempt < max_retries:
                    import asyncio as _aio
                    delay = min(2 ** attempt, 30)
                    logger.warning("Anthropic connection error %s (attempt %d/%d), retrying in %.1fs",
                        type(e).__name__, attempt + 1, max_retries + 1, delay)
                    await _aio.sleep(delay)
                    continue
                raise

    def list_models(self) -> list[str]:
        return [
            "claude-opus-4-20250514",
            "claude-sonnet-4-20250514",
            "claude-3-5-haiku-20241022",
            "claude-3-5-sonnet-20241022",
        ]
