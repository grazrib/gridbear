"""Utilities module for MS365 plugin."""

from .retry import RetryConfig, retry_with_backoff

__all__ = ["retry_with_backoff", "RetryConfig"]
