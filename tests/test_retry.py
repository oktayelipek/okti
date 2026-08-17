"""Tests for retry_with_backoff — provider HTTP retry policy."""

from __future__ import annotations

import httpx
import pytest

from okti.models import retry as retry_mod
from okti.models.retry import retry_with_backoff


@pytest.fixture(autouse=True)
def _no_sleep_or_jitter(monkeypatch):
    """Make retries instant and deterministic."""
    async def _instant_sleep(_):
        return None

    monkeypatch.setattr(retry_mod.asyncio, "sleep", _instant_sleep)
    monkeypatch.setattr(retry_mod.random, "uniform", lambda a, b: 0.0)


def _http_error(status: int, headers: dict[str, str] | None = None) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.test")
    response = httpx.Response(status, headers=headers or {}, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


async def test_success_on_first_try_no_retries():
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        return "ok"

    result = await retry_with_backoff(fn, max_retries=3)
    assert result == "ok"
    assert calls == 1


async def test_retries_on_500_then_succeeds():
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise _http_error(500)
        return "ok"

    result = await retry_with_backoff(fn, max_retries=3, base_delay=0.0)
    assert result == "ok"
    assert calls == 3


async def test_non_retryable_status_raises_immediately():
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        raise _http_error(400)

    with pytest.raises(httpx.HTTPStatusError):
        await retry_with_backoff(fn, max_retries=3, base_delay=0.0)
    assert calls == 1  # no retries for 4xx (except 429)


async def test_429_respects_retry_after_header():
    calls = 0
    sleeps: list[float] = []

    async def capture_sleep(delay):
        sleeps.append(delay)

    async def fn():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _http_error(429, headers={"retry-after": "7"})
        return "ok"

    import okti.models.retry as m
    m.asyncio.sleep = capture_sleep  # type: ignore[assignment]
    try:
        result = await retry_with_backoff(fn, max_retries=3, base_delay=0.1, max_delay=30.0)
    finally:
        # autouse fixture will re-monkeypatch next test
        pass
    assert result == "ok"
    assert sleeps and sleeps[0] >= 7.0


async def test_429_with_invalid_retry_after_falls_back_to_backoff():
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _http_error(429, headers={"retry-after": "not-a-number"})
        return "ok"

    result = await retry_with_backoff(fn, max_retries=2, base_delay=0.0)
    assert result == "ok"
    assert calls == 2


async def test_exhausts_retries_and_raises_last_error():
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        raise _http_error(503)

    with pytest.raises(httpx.HTTPStatusError):
        await retry_with_backoff(fn, max_retries=2, base_delay=0.0)
    assert calls == 3  # initial + 2 retries


async def test_connect_error_is_retried():
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        if calls < 2:
            raise httpx.ConnectError("no network")
        return "ok"

    result = await retry_with_backoff(fn, max_retries=3, base_delay=0.0)
    assert result == "ok"
    assert calls == 2


async def test_read_timeout_exhausts_and_reraises():
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("slow")

    with pytest.raises(httpx.ReadTimeout):
        await retry_with_backoff(fn, max_retries=1, base_delay=0.0)
    assert calls == 2


async def test_kwargs_and_args_are_forwarded():
    async def fn(a, b, *, c):
        return (a, b, c)

    result = await retry_with_backoff(fn, 1, 2, c=3, max_retries=0)
    assert result == (1, 2, 3)
