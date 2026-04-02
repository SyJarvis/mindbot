"""Static tool registry – stores and retrieves tools by name."""

from __future__ import annotations

from typing import Iterable

from src.mindbot.capability.backends.tooling.models import Tool


class ToolRegistry:
    """Instance-based static tool registry.

    Unlike a class-level singleton, each registry is independent so that
    different agents / contexts can have their own tool sets.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, tool: Tool) -> None:
        """Register a tool.  Overwrites any existing tool with the same name."""
        self._tools[tool.name] = tool

    def register_many(self, tools: Iterable[Tool]) -> None:
        """Register multiple tools at once."""
        for t in tools:
            self.register(t)

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get(self, name: str) -> Tool | None:
        """Retrieve a tool by *name*, or ``None``."""
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        """Return all registered tools."""
        return list(self._tools.values())

    def names(self) -> list[str]:
        """Return sorted names of all registered tools."""
        return sorted(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_tools(cls, tools: Iterable[Tool]) -> "ToolRegistry":
        """Create a registry pre-populated with *tools*."""
        registry = cls()
        registry.register_many(tools)
        return registry
