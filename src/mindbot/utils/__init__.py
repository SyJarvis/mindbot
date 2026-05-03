"""Shared utility functions for the Mindbot framework."""

from __future__ import annotations

import asyncio
import re
from functools import wraps
from typing import Any, Callable, TypeVar

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def get_logger(name: str) -> Any:
    """Backward-compatibility shim — returns the global loguru logger.

    New code should import ``logger`` directly::

        from mindbot.logging import logger

    This shim exists so that modules not yet migrated continue to work.
    The returned object is the same loguru ``logger`` singleton, so all
    log records flow through the unified pipeline configured in
    ``mindbot.logging.setup_logging``.
    """
    from mindbot.logging import logger  # noqa: PLC0415

    return logger


# ---------------------------------------------------------------------------
# Token counting (simple estimation – swap in tiktoken later)
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"\S+")


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~1 token per 0.75 words (English heuristic).

    For CJK text each character is ~1 token; for English ~4 chars per token.
    This is intentionally cheap – callers needing accuracy should use tiktoken.
    """
    # Heuristic: count words, multiply by 1.3 for sub-word pieces.
    words = _WORD_RE.findall(text)
    return max(1, int(len(words) * 1.3))


# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------

class RetryableError(Exception):
    """Raise this (or a subclass) to indicate the operation may be retried."""


def with_retry(
    max_retries: int = 3,
    backoff: float = 1.0,
    retryable: tuple[type[BaseException], ...] = (RetryableError,),
) -> Callable:
    """Async retry decorator with exponential back-off.

    Usage::

        @with_retry(max_retries=3)
        async def call_api(...):
            ...
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: BaseException | None = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except retryable as exc:
                    last_exc = exc
                    if attempt < max_retries - 1:
                        wait = backoff * (2 ** attempt)
                        await asyncio.sleep(wait)
            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------

def run_sync(coro: Any) -> Any:
    """Run an async coroutine from a synchronous context.

    Works regardless of whether there is already a running event loop in the
    current thread.  When an event loop is running (e.g. inside an async
    function), the coroutine is executed in a separate thread with its own
    fresh event loop to avoid blocking or nesting.
    """
    import concurrent.futures

    try:
        asyncio.get_running_loop()
        # A loop is already running – execute in a worker thread.
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    except RuntimeError:
        # No running loop – create one in the current thread.
        return asyncio.run(coro)


def truncate(text: str, max_length: int = 2000, suffix: str = "...") -> str:
    """Truncate *text* to *max_length* characters, appending *suffix* if cut."""
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix
