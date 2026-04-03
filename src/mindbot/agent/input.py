"""User input management for agent execution.

This module provides mechanisms for the agent to request additional
input from the user during execution.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Callable

from mindbot.agent.models import AgentEvent, InputRequest


@dataclass
class PendingInputRequest:
    """A pending input request waiting for user response."""
    request: InputRequest
    future: asyncio.Future[str]
    created_at: float


class InputManager:
    """Manages user input requests during agent execution.

    The input manager allows the agent to pause execution and request
    additional information from the user when needed.

    Usage:
        manager = InputManager()

        # In agent execution
        user_input = await manager.request_input(
            InputRequest(
                request_id=str(uuid.uuid4()),
                question="What is your name?",
                timeout=300,
            ),
            on_event=lambda e: print(e),
        )

        # In user interface (separate thread/async context)
        manager.provide_input(request_id, "John Doe")
    """

    def __init__(self, default_timeout: float = 300) -> None:
        """Initialize the input manager.

        Args:
            default_timeout: Default timeout for input requests (seconds)
        """
        self.default_timeout = default_timeout
        self._pending: dict[str, PendingInputRequest] = {}
        self._lock = asyncio.Lock()

    async def request_input(
        self,
        question: str,
        on_event: Callable[[AgentEvent], None] | None = None,
        timeout: float | None = None,
        request_id: str | None = None,
    ) -> str:
        """Request input from the user.

        This method:
        1. Creates an input request
        2. Sends request event
        3. Waits for user input
        4. Returns the user's response

        Args:
            question: The question to ask the user
            on_event: Optional callback for events
            timeout: Timeout in seconds (uses default if None)
            request_id: Optional request ID (auto-generated if None)

        Returns:
            The user's input as a string

        Raises:
            asyncio.TimeoutError: If input request times out
        """
        if timeout is None:
            timeout = self.default_timeout

        if request_id is None:
            request_id = str(uuid.uuid4())

        request = InputRequest(
            request_id=request_id,
            question=question,
            timeout=timeout,
        )

        # Send request event
        if on_event:
            on_event(AgentEvent.user_input_request(
                question=question,
                request_id=request_id,
            ))

        # Wait for input
        return await self._wait_for_input(request)

    async def _wait_for_input(self, request: InputRequest) -> str:
        """Wait for user input with timeout."""
        async with self._lock:
            future: asyncio.Future[str] = asyncio.Future()
            self._pending[request.request_id] = PendingInputRequest(
                request=request,
                future=future,
                created_at=asyncio.get_event_loop().time(),
            )

        try:
            # Wait for input with timeout
            input_text = await asyncio.wait_for(future, timeout=request.timeout)
            return input_text
        except asyncio.TimeoutError:
            # Clean up on timeout
            async with self._lock:
                self._pending.pop(request.request_id, None)
            raise
        finally:
            # Clean up after input
            async with self._lock:
                self._pending.pop(request.request_id, None)

    def provide_input(self, request_id: str, input_text: str) -> None:
        """Provide input for a pending request.

        This is called from the user interface when the user provides input.

        Args:
            request_id: The ID of the request to resolve
            input_text: The user's input

        Raises:
            KeyError: If request_id is not found
        """
        pending = self._pending.get(request_id)
        if pending is None:
            raise KeyError(f"Request {request_id} not found or already resolved")

        future = pending.future
        if not future.done():
            future.set_result(input_text)

    def get_pending_requests(self) -> list[InputRequest]:
        """Get all pending input requests.

        Returns:
            List of pending requests
        """
        return [pending.request for pending in self._pending.values()]

    def cancel_all(self) -> None:
        """Cancel all pending input requests."""
        for pending in list(self._pending.values()):
            if not pending.future.done():
                pending.future.cancel()
        self._pending.clear()
