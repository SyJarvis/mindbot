"""Runtime manager for dynamic tool creation and refresh."""

from __future__ import annotations

from typing import Any

from mindbot.capability.backends.tool_backend import ToolBackend
from mindbot.capability.facade import CapabilityFacade
from mindbot.generation.events import ToolEvent, ToolEventBus, ToolEventType
from mindbot.generation.models import ImplementationType, ToolDefinition
from mindbot.generation.protocols import GenerationPersistenceError, GenerationRequest
from mindbot.generation.tool_generator import PromptStrategy, ToolGenerator


class DynamicToolManager:
    """Coordinates generation, persistence, registration, and refresh."""

    def __init__(
        self,
        *,
        llm: Any,
        capability_facade: CapabilityFacade,
        tool_backend: ToolBackend,
        event_bus: ToolEventBus | None = None,
    ) -> None:
        self._llm = llm
        self._facade = capability_facade
        self._tool_backend = tool_backend
        self._event_bus = event_bus or ToolEventBus()

    @property
    def event_bus(self) -> ToolEventBus:
        """The lifecycle event bus."""
        return self._event_bus

    def load_persisted_tools(self) -> int:
        """Load persisted definitions and refresh the capability index."""
        loaded = self._tool_backend.load_definitions()
        self._facade.refresh_registry()
        return loaded

    def list_dynamic_tools(self) -> list[ToolDefinition]:
        """Return all dynamic tool definitions."""
        return self._tool_backend.list_dynamic_definitions()

    async def create_tool_definition(
        self,
        description: str,
        *,
        hints: dict[str, Any] | None = None,
    ) -> ToolDefinition:
        """Generate a validated ToolDefinition from natural language."""
        generator = ToolGenerator(PromptStrategy(self._llm))
        request = GenerationRequest(description=description, hints=hints or {})
        result = await generator.generate(request)
        if not result.succeeded or result.artifact is None:
            raise ValueError(result.error or "Failed to generate tool definition")
        return result.artifact

    async def register_and_persist(
        self,
        description: str,
        *,
        hints: dict[str, Any] | None = None,
        replace: bool = False,
        persist: bool = True,
        implementation_type: ImplementationType | None = None,
        implementation_ref: str | None = None,
    ) -> ToolDefinition:
        """Generate, register, persist, and refresh a new dynamic tool."""
        defn = await self.create_tool_definition(description, hints=hints)
        if hints:
            if isinstance(hints.get("name"), str) and hints["name"].strip():
                defn.name = hints["name"].strip()
            if isinstance(hints.get("parameters_schema"), dict):
                defn.parameters_schema = hints["parameters_schema"]
        if implementation_type is not None:
            defn.implementation_type = implementation_type
        if implementation_ref is not None:
            defn.implementation_ref = implementation_ref

        try:
            self._tool_backend.register_dynamic(defn, replace=replace, persist=persist)
        except OSError as exc:
            raise GenerationPersistenceError(defn.id, exc) from exc

        self._facade.refresh_registry()
        await self._event_bus.publish(
            ToolEvent(
                type=ToolEventType.CREATED,
                tool_id=defn.id,
                tool_name=defn.name,
                metadata={"persist": persist},
            )
        )
        return defn

    async def remove_tool(self, key: str) -> bool:
        """Remove a dynamic tool by ID or name and refresh the facade."""
        defn = next(
            (item for item in self._tool_backend.list_dynamic_definitions() if item.id == key or item.name == key),
            None,
        )
        removed = self._tool_backend.remove_dynamic(key)
        if removed:
            self._facade.refresh_registry()
            if defn is not None:
                await self._event_bus.publish(
                    ToolEvent(
                        type=ToolEventType.REMOVED,
                        tool_id=defn.id,
                        tool_name=defn.name,
                    )
                )
        return removed

    async def reload_tools(self) -> int:
        """Reload persisted dynamic tools from disk and refresh capabilities."""
        loaded = self.load_persisted_tools()
        await self._event_bus.publish(
            ToolEvent(
                type=ToolEventType.RELOADED,
                tool_id="*",
                tool_name="*",
                metadata={"loaded": loaded},
            )
        )
        return loaded
