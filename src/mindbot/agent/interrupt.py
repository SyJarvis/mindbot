"""User interrupt mechanism for agent execution.

This module provides a way for users to interrupt/abort agent execution,
similar to OpenClaw's process management.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import Callable


@dataclass
class InterruptSignal:
    """A signal that can be used to interrupt agent execution.

    This is thread-safe and can be used to signal interruption from
    any thread.
    """
    _aborted: bool = False
    _lock: threading.Lock = threading.Lock()

    @property
    def aborted(self) -> bool:
        """Check if execution has been aborted."""
        with self._lock:
            return self._aborted

    def abort(self) -> None:
        """Signal that execution should be aborted."""
        with self._lock:
            self._aborted = True

    def reset(self) -> None:
        """Reset the abort signal (for re-use)."""
        with self._lock:
            self._aborted = False


class AgentExecution:
    """Manages an agent execution session with interrupt support.

    This class provides:
    1. A way to check for interruption during execution
    2. A method to abort execution from another thread
    3. Integration with asyncio for async execution

    Usage:
        execution = AgentExecution()

        # In agent execution loop
        if await execution.check_interrupted():
            raise InterruptedError("Execution aborted by user")

        # From user interface (e.g., Ctrl+C handler)
        execution.abort()
    """

    def __init__(self) -> None:
        """Initialize a new execution session."""
        self.signal = InterruptSignal()
        self._event = asyncio.Event()

    async def check_interrupted(self) -> bool:
        """Check if execution has been interrupted.

        This is an async method that yields control to the event loop,
        allowing the abort signal to be processed.

        Returns:
            True if execution should be aborted
        """
        # Small sleep to allow signal propagation
        await asyncio.sleep(0)
        return self.signal.aborted

    def abort(self) -> None:
        """Abort the execution.

        This can be called from any thread (e.g., a signal handler).
        """
        self.signal.abort()

    def reset(self) -> None:
        """Reset the execution state for re-use."""
        self.signal.reset()
        self._event.clear()

    @property
    def is_aborted(self) -> bool:
        """Check if execution has been aborted (synchronous)."""
        return self.signal.aborted


class InterruptException(Exception):
    """Exception raised when execution is interrupted by user."""

    pass


async def with_interrupt_check(
    execution: AgentExecution,
    coro,
    on_event: Callable | None = None,
) -> any:
    """Execute a coroutine with interrupt checking.

    This wrapper periodically checks for interruption and raises
    InterruptException if aborted.

    Args:
        execution: The execution session
        coro: The coroutine to execute
        on_event: Optional event callback

    Returns:
        The result of the coroutine

    Raises:
        InterruptException: If execution is aborted
    """
    task = asyncio.create_task(coro)

    while not task.done():
        if await execution.check_interrupted():
            task.cancel()
            if on_event:
                from mindbot.agent.models import AgentEvent
                on_event(AgentEvent.aborted())
            raise InterruptException("Execution aborted by user")
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=0.1)
        except asyncio.TimeoutError:
            continue
        except asyncio.CancelledError:
            raise InterruptException("Execution aborted by user")

    return task.result()
