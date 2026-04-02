"""Lightweight tool lifecycle events."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ToolEventType(str, Enum):
    """Lifecycle events for generated tools."""

    CREATED = "created"
    REMOVED = "removed"
    RELOADED = "reloaded"


@dataclass(slots=True)
class ToolEvent:
    """A single tool lifecycle event."""

    type: ToolEventType
    tool_id: str
    tool_name: str
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolEventBus:
    """Minimal in-memory async event bus."""

    def __init__(self) -> None:
        self._subscribers: list[Callable[[ToolEvent], Awaitable[None] | None]] = []

    def subscribe(self, callback: Callable[[ToolEvent], Awaitable[None] | None]) -> None:
        """Register an event subscriber."""
        self._subscribers.append(callback)

    async def publish(self, event: ToolEvent) -> None:
        """Publish an event to all subscribers."""
        for callback in list(self._subscribers):
            result = callback(event)
            if result is not None:
                await result
