"""Retry utilities with exponential backoff."""

import asyncio
from dataclasses import dataclass
from functools import wraps
from typing import Callable, TypeVar

from config.logging_config import logger

T = TypeVar("T")


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""

    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 32.0
    exponential_base: float = 2.0
    retryable_status_codes: tuple[int, ...] = (429, 500, 502, 503, 504)


async def retry_with_backoff(
    func: Callable[..., T],
    *args,
    config: RetryConfig | None = None,
    **kwargs,
) -> T:
    """Execute function with exponential backoff retry.

    Args:
        func: Async function to execute
        *args: Positional arguments for func
        config: Retry configuration
        **kwargs: Keyword arguments for func

    Returns:
        Result from successful function call

    Raises:
        Last exception if all retries fail
    """
    if config is None:
        config = RetryConfig()

    last_exception = None
    delay = config.base_delay

    for attempt in range(config.max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_exception = e

            # Check if we should retry
            should_retry = False
            status_code = getattr(e, "status_code", None)

            if status_code in config.retryable_status_codes:
                should_retry = True
            elif "timeout" in str(e).lower():
                should_retry = True

            if not should_retry or attempt >= config.max_retries:
                raise

            # Calculate delay with jitter
            jitter = delay * 0.1 * (0.5 - asyncio.get_event_loop().time() % 1)
            actual_delay = min(delay + jitter, config.max_delay)

            logger.warning(
                f"Retry {attempt + 1}/{config.max_retries} after {actual_delay:.2f}s: {e}"
            )

            await asyncio.sleep(actual_delay)
            delay = min(delay * config.exponential_base, config.max_delay)

    raise last_exception


def with_retry(config: RetryConfig | None = None):
    """Decorator for automatic retry with backoff.

    Args:
        config: Retry configuration

    Returns:
        Decorated function
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            return await retry_with_backoff(func, *args, config=config, **kwargs)

        return wrapper

    return decorator
