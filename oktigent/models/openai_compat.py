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


def estimate_cost(model_name: str, prompt_tokens: int, completion_tokens: int, cache_read: int = 0) -> float:
    """Estimate USD cost based on model pricing per million tokens."""
    m = (model_name or "").lower()
    if ":free" in m or "free" in m:
        return 0.0

    if "claude-3-7" in m or "claude-3.7" in m or "claude-3-5" in m or "claude-3.5" in m:
        p_rate, c_rate, cr_rate = 3.0, 15.0, 0.30
    elif "haiku" in m:
        p_rate, c_rate, cr_rate = 0.80, 4.0, 0.08
    elif "gpt-4o-mini" in m or "o3-mini" in m:
        p_rate, c_rate, cr_rate = 0.15, 0.60, 0.075
    elif "gpt-4o" in m:
        p_rate, c_rate, cr_rate = 2.50, 10.0, 1.25
    elif "deepseek" in m:
        p_rate, c_rate, cr_rate = 0.14, 0.28, 0.014
    elif "gemini-2" in m or "gemini-1.5-flash" in m:
        p_rate, c_rate, cr_rate = 0.10, 0.40, 0.025
    else:
        p_rate, c_rate, cr_rate = 0.50, 1.50, 0.10

    uncached_prompt = max(0, prompt_tokens - cache_read)
    cost = (uncached_prompt * p_rate + cache_read * cr_rate + completion_tokens * c_rate) / 1_000_000.0
    return round(cost, 6)


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
            headers["HTTP-Referer"] = "https://github.com/oktayelipek/oktigent"
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
        from oktigent.models.retry import retry_with_backoff

        payload = self._build_payload(messages, tools, model, max_tokens, temperature, stream=False)

        async def _call():
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=self._headers(),
                )
                resp.raise_for_status()
                return resp.json()

        data = await retry_with_backoff(_call)

        choice = data["choices"][0]
        msg = choice["message"]
        u_data = data.get("usage", {})
        prompt_tokens = u_data.get("prompt_tokens", 0)
        completion_tokens = u_data.get("completion_tokens", 0)
        total_tokens = u_data.get("total_tokens", 0) or (prompt_tokens + completion_tokens)
        cache_read = (
            u_data.get("prompt_tokens_details", {}).get("cached_tokens", 0)
            or u_data.get("cache_read_input_tokens", 0)
            or 0
        )
        cache_write = u_data.get("cache_creation_input_tokens", 0) or 0
        active_model = data.get("model", model or "")
        cost = estimate_cost(active_model, prompt_tokens, completion_tokens, cache_read)

        usage = TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            cost_usd=cost,
        )

        tool_calls = [ToolCall.from_raw(tc) for tc in msg.get("tool_calls", [])]

        message = Message(
            role=Role.ASSISTANT,
            content=msg.get("content") or msg.get("reasoning") or msg.get("thinking") or "",
            tool_calls=tool_calls,
            model=active_model,
        )
        return ProviderResponse(message=message, usage=usage, model=active_model)

    async def stream_chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[StreamChunk]:
        payload = self._build_payload(messages, tools, model, max_tokens, temperature, stream=True)

        max_retries = 3
        for attempt in range(max_retries + 1):
            try:
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

                            # Retry on rate limit / server errors
                            if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                                import asyncio as _aio
                                delay = 2 ** attempt
                                retry_after = resp.headers.get("retry-after", "")
                                try:
                                    delay = max(delay, float(retry_after))
                                except (ValueError, TypeError):
                                    pass
                                logger.warning("HTTP %d (attempt %d/%d), retrying in %.1fs",
                                    resp.status_code, attempt + 1, max_retries + 1, delay)
                                await _aio.sleep(delay)
                                continue

                            if resp.status_code in (400, 422) and tools:
                                logger.warning("Provider %s rejected tools schema. Retrying without tools...", self.provider_name)
                                async for chunk in self.stream_chat(messages, tools=None, model=model, max_tokens=max_tokens, temperature=temperature):
                                    yield chunk
                                return

                            raise RuntimeError(f"[{self.provider_name.capitalize()} API Error {resp.status_code}]: {err_msg}")

                        # Success — process the stream
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

                            content = delta.get("content") or ""
                            reasoning = delta.get("reasoning") or delta.get("thinking") or ""
                            if content:
                                yield StreamChunk(content_delta=content)
                            elif reasoning:
                                yield StreamChunk(content_delta=reasoning)

                            for tc_delta in delta.get("tool_calls", []):
                                func = tc_delta.get("function", {})
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
                                u_data = data.get("usage", {})
                                p_tok = u_data.get("prompt_tokens", 0)
                                c_tok = u_data.get("completion_tokens", 0)
                                tot_tok = u_data.get("total_tokens", 0) or (p_tok + c_tok)
                                c_read = (
                                    u_data.get("prompt_tokens_details", {}).get("cached_tokens", 0)
                                    or u_data.get("cache_read_input_tokens", 0)
                                    or 0
                                )
                                c_write = u_data.get("cache_creation_input_tokens", 0) or 0
                                m_name = data.get("model", model or "")
                                cost = estimate_cost(m_name, p_tok, c_tok, c_read)

                                yield StreamChunk(
                                    finish_reason=finish,
                                    token_usage=TokenUsage(
                                        prompt_tokens=p_tok,
                                        completion_tokens=c_tok,
                                        total_tokens=tot_tok,
                                        cache_read_tokens=c_read,
                                        cache_write_tokens=c_write,
                                        cost_usd=cost,
                                    ),
                                )
                        return  # Stream completed successfully

            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as e:
                if attempt < max_retries:
                    import asyncio as _aio
                    delay = min(2 ** attempt, 30)
                    logger.warning("Connection error %s (attempt %d/%d), retrying in %.1fs",
                        type(e).__name__, attempt + 1, max_retries + 1, delay)
                    await _aio.sleep(delay)
                    continue
                raise
            except Exception as e:
                logger.error("Stream error from %s: %s", self.provider_name, e)
                yield StreamChunk(content_delta=f"\n\n[Stream error: {e}]", finish_reason="error")
                return

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
