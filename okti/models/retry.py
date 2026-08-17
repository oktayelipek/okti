"""Retry utility with exponential backoff for provider HTTP calls."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Status codes that should trigger a retry
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


async def retry_with_backoff(
    func: Callable[..., Awaitable[T]],
    *args,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    **kwargs,
) -> T:
    """Execute an async function with exponential backoff on transient errors.

    Retries on:
    - httpx.HTTPStatusError with status 429, 500, 502, 503, 504
    - httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout

    Args:
        func: Async function to call
        max_retries: Maximum number of retries
        base_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
    """
    last_exception: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except httpx.HTTPStatusError as e:
            last_exception = e
            status = e.response.status_code
            if status not in _RETRYABLE_STATUS_CODES:
                raise  # Non-retryable HTTP error
            if attempt == max_retries:
                raise
            # Check for Retry-After header (429)
            retry_after = 0.0
            if status == 429:
                retry_after_header = e.response.headers.get("retry-after", "")
                try:
                    retry_after = float(retry_after_header)
                except (ValueError, TypeError):
                    pass
            delay = max(retry_after, min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay))
            logger.warning(
                "HTTP %d (attempt %d/%d), retrying in %.1fs",
                status, attempt + 1, max_retries + 1, delay,
            )
            await asyncio.sleep(delay)
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as e:
            last_exception = e
            if attempt == max_retries:
                raise
            delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
            logger.warning(
                "Connection error %s (attempt %d/%d), retrying in %.1fs",
                type(e).__name__, attempt + 1, max_retries + 1, delay,
            )
            await asyncio.sleep(delay)

    assert last_exception is not None
    raise last_exception
