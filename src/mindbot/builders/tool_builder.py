"""Tool builder – helpers for building ToolRegistry instances.

The ``@tool`` decorator remains the primary way to *define* tools.  This
module adds a convenience layer for *assembling* them into a registry,
which is useful when you want to compose tools across modules or when
building agent instances programmatically.

Usage::

    from mindbot.builders import create_tool_registry
    from mindbot.capability.backends.tooling import tool

    @tool()
    def get_weather(city: str) -> str:
        ...

    registry = create_tool_registry([get_weather, other_tool])
"""

from __future__ import annotations

from typing import Any

from mindbot.capability.backends.tooling import ToolRegistry


def create_tool_registry(tools: list[Any] | None = None) -> ToolRegistry:
    """Create a :class:`~mindbot.capability.backends.tooling.ToolRegistry`.

    Args:
        tools: Zero or more :class:`~mindbot.capability.backends.tooling.models.Tool`
            instances (e.g. produced by the ``@tool`` decorator).

    Returns:
        A ``ToolRegistry`` pre-populated with *tools*.
    """
    return ToolRegistry.from_tools(tools or [])
