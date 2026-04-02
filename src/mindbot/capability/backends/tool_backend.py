"""ToolBackend – ExtensionBackend implementation for tools.

This backend aggregates *static* tools (Python callables registered at
import time) and *dynamic* tools (LLM-generated
:class:`~mindbot.generation.models.ToolDefinition` instances loaded from
``~/.mindbot/tools/``) and exposes them as a unified list of
:class:`~mindbot.capability.models.Capability` objects.

Routing
-------
- ``capability_id`` that matches a static tool name → dispatched to
  :class:`~mindbot.capability.backends.tooling.executor.ToolExecutor`.
- ``capability_id`` that matches a :class:`~mindbot.generation.models.ToolDefinition`
  ID → dispatched to :class:`~mindbot.generation.executor.DynamicToolExecutor`.
- Same ``capability_id`` in both → explicit conflict raised at registration
  time; no silent overwrite.

Startup loading
---------------
Call :meth:`load_definitions` (or pass ``auto_load=True`` to ``__init__``)
to load all persisted :class:`~mindbot.generation.models.ToolDefinition`
objects from the store directory and register them in this backend.

Runtime incremental registration
---------------------------------
After generating a new :class:`~mindbot.generation.models.ToolDefinition`,
call :meth:`register_dynamic` to add it to this backend's routing table
and persist it.  Then call
:attr:`~mindbot.capability.facade.CapabilityFacade.refresh_registry` on the
facade to make it visible to the resolution layer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.mindbot.capability.backends.base import ExtensionBackend
from src.mindbot.capability.backends.tooling.executor import ToolExecutor
from src.mindbot.capability.backends.tooling.models import Tool
from src.mindbot.capability.backends.tooling.registry import ToolRegistry
from src.mindbot.capability.models import (
    Capability,
    CapabilityConflictError,
    CapabilityExecutionError,
    CapabilityNotFoundError,
    CapabilityType,
)
from src.mindbot.context.models import ToolCall
from src.mindbot.generation.executor import DynamicToolExecutor
from src.mindbot.generation.models import ToolDefinition
from src.mindbot.generation.registry import ToolDefinitionRegistry
from src.mindbot.utils import get_logger

logger = get_logger("capability.backends.tool_backend")


class ToolBackend:
    """Unified tool backend satisfying the
    :class:`~mindbot.capability.backends.base.ExtensionBackend` protocol.

    Args:
        static_registry: Pre-populated static tool registry, or *None* for an
            empty one.
        definition_registry: Persistent definition registry, or *None* to
            create a fresh one (with the default store directory).
        auto_load: When *True*, :meth:`load_definitions` is called during
            ``__init__``, loading all persisted dynamic tools immediately.
    """

    def __init__(
        self,
        static_registry: ToolRegistry | None = None,
        definition_registry: ToolDefinitionRegistry | None = None,
        *,
        auto_load: bool = False,
    ) -> None:
        self._static_registry: ToolRegistry = static_registry or ToolRegistry()
        self._def_registry: ToolDefinitionRegistry = (
            definition_registry or ToolDefinitionRegistry()
        )
        self._dynamic_executor = DynamicToolExecutor()

        # capability_id -> "static" | "dynamic"
        self._routing: dict[str, str] = {}
        # exposed tool name -> capability_id
        self._name_index: dict[str, str] = {}

        # Transient (non-persisted) dynamic tools, keyed by definition id
        self._transient: dict[str, ToolDefinition] = {}

        # Index static tools immediately
        for tool in self._static_registry.list_tools():
            self._index_static(tool, raise_on_conflict=False)

        if auto_load:
            self.load_definitions()

    # ------------------------------------------------------------------
    # ExtensionBackend protocol
    # ------------------------------------------------------------------

    def type_id(self) -> str:
        return "tool"

    def list_capabilities(self) -> list[Capability]:
        """Return capabilities for all registered static and dynamic tools."""
        caps: list[Capability] = []
        seen: set[str] = set()

        for tool in self._static_registry.list_tools():
            cap = _tool_to_capability(tool)
            if cap.id not in seen:
                caps.append(cap)
                seen.add(cap.id)

        # Persisted dynamic tools
        for defn in self._def_registry.list_all():
            cap = _definition_to_capability(defn)
            if cap.id not in seen:
                caps.append(cap)
                seen.add(cap.id)

        # Transient (non-persisted) dynamic tools
        for defn in self._transient.values():
            cap = _definition_to_capability(defn)
            if cap.id not in seen:
                caps.append(cap)
                seen.add(cap.id)

        return caps

    async def execute(
        self,
        capability_id: str,
        arguments: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> str:
        """Route execution to the appropriate executor.

        Args:
            capability_id: Capability ID to execute.
            arguments: Call arguments.
            context: Optional session / step context.

        Returns:
            String result.

        Raises:
            CapabilityNotFoundError: When *capability_id* is unknown.
            CapabilityExecutionError: When the executor raises at runtime.
        """
        route = self._routing.get(capability_id)

        if route == "static":
            return await self._execute_static(capability_id, arguments)

        if route == "dynamic":
            return await self._execute_dynamic(capability_id, arguments, context)

        raise CapabilityNotFoundError(capability_id)

    # ------------------------------------------------------------------
    # Static tool management
    # ------------------------------------------------------------------

    def register_static(self, tool: Tool, *, replace: bool = False) -> None:
        """Add a static tool to this backend.

        Args:
            tool: The static tool to register.
            replace: When *False* (default), raises if the capability ID
                already exists.  When *True*, silently replaces it.

        Raises:
            CapabilityConflictError: On ID collision when *replace* is *False*.
        """
        self._index_static(tool, raise_on_conflict=not replace)
        self._static_registry.register(tool)

    def _index_static(self, tool: Tool, *, raise_on_conflict: bool = True) -> None:
        cap_id = tool.name  # static tools: capability_id == tool name
        existing = self._routing.get(cap_id)
        if existing is not None and raise_on_conflict:
            raise CapabilityConflictError(cap_id)
        self._index_name(tool.name, cap_id, raise_on_conflict=raise_on_conflict)
        self._routing[cap_id] = "static"

    async def _execute_static(self, capability_id: str, arguments: dict[str, Any]) -> str:
        tool = self._static_registry.get(capability_id)
        if tool is None:
            raise CapabilityNotFoundError(capability_id)

        fake_call = ToolCall(id="cap-exec", name=capability_id, arguments=arguments)
        executor = ToolExecutor(self._static_registry)
        result = await executor.execute(fake_call)
        if result.success:
            return result.content
        raise CapabilityExecutionError(capability_id, cause=Exception(result.error))

    # ------------------------------------------------------------------
    # Dynamic tool management
    # ------------------------------------------------------------------

    def load_definitions(self) -> int:
        """Load all persisted definitions and index them for routing.

        Returns:
            Number of definitions loaded and indexed.
        """
        loaded = self._def_registry.load_all()
        for defn in self._def_registry.list_all():
            self._index_dynamic(defn, raise_on_conflict=False)
        logger.info("ToolBackend loaded %d dynamic tool definitions", loaded)
        return loaded

    def register_dynamic(
        self,
        defn: ToolDefinition,
        *,
        replace: bool = False,
        persist: bool = True,
    ) -> None:
        """Register a dynamic tool definition at runtime.

        After registration, call
        :meth:`~mindbot.capability.facade.CapabilityFacade.refresh_registry`
        on the owning facade to make the new capability visible to the
        resolution layer.

        Args:
            defn: The :class:`~mindbot.generation.models.ToolDefinition` to
                register.
            replace: When *True*, an existing entry with the same capability
                ID is replaced.
            persist: When *True* (default), the definition is written to disk
                via the :class:`~mindbot.generation.registry.ToolDefinitionRegistry`.
                When *False*, the definition is kept in memory only.

        Raises:
            CapabilityConflictError: On ID collision when *replace* is *False*.
        """
        self._index_dynamic(defn, raise_on_conflict=not replace)
        if persist:
            self._def_registry.save(defn, replace=replace)
        else:
            self._transient[defn.id] = defn

    def _index_dynamic(self, defn: ToolDefinition, *, raise_on_conflict: bool = True) -> None:
        cap_id = defn.id
        existing = self._routing.get(cap_id)
        if existing is not None and raise_on_conflict:
            raise CapabilityConflictError(cap_id)
        self._index_name(defn.name, cap_id, raise_on_conflict=raise_on_conflict)
        self._routing[cap_id] = "dynamic"

    async def _execute_dynamic(
        self,
        capability_id: str,
        arguments: dict[str, Any],
        context: dict[str, Any] | None,
    ) -> str:
        defn = self._def_registry.get_by_id(capability_id) or self._transient.get(capability_id)
        if defn is None:
            raise CapabilityNotFoundError(capability_id)
        return await self._dynamic_executor.execute(defn, arguments, context)

    def list_dynamic_definitions(self) -> list[ToolDefinition]:
        """Return all persisted and transient dynamic definitions."""
        return [*self._def_registry.list_all(), *self._transient.values()]

    def remove_dynamic(self, key: str) -> bool:
        """Remove a dynamic definition by ID or name."""
        defn = (
            self._def_registry.get_by_id(key)
            or self._def_registry.get_by_name(key)
            or self._transient.get(key)
            or next((item for item in self._transient.values() if item.name == key), None)
        )
        if defn is None:
            return False

        if self._def_registry.get_by_id(defn.id) is not None:
            self._def_registry.delete(defn.id)
        else:
            self._transient.pop(defn.id, None)

        self._routing.pop(defn.id, None)
        self._name_index.pop(defn.name, None)
        return True

    def _index_name(
        self,
        name: str,
        capability_id: str,
        *,
        raise_on_conflict: bool,
    ) -> None:
        existing = self._name_index.get(name)
        if existing is not None and existing != capability_id and raise_on_conflict:
            raise CapabilityConflictError(name)
        self._name_index[name] = capability_id


# ------------------------------------------------------------------
# Conversion helpers
# ------------------------------------------------------------------


def _tool_to_capability(tool: Tool) -> Capability:
    """Convert a static :class:`~mindbot.capability.backends.tooling.models.Tool`
    to a :class:`~mindbot.capability.models.Capability`."""
    return Capability(
        id=tool.name,
        name=tool.name,
        description=tool.description,
        parameters_schema=tool.parameters_json_schema(),
        capability_type=CapabilityType.TOOL,
        backend_id=tool.name,
    )


def _definition_to_capability(defn: ToolDefinition) -> Capability:
    """Convert a :class:`~mindbot.generation.models.ToolDefinition`
    to a :class:`~mindbot.capability.models.Capability`."""
    return Capability(
        id=defn.id,
        name=defn.name,
        description=defn.description,
        parameters_schema=defn.parameters_schema,
        capability_type=CapabilityType.TOOL,
        backend_id=defn.id,
    )


assert isinstance(ToolBackend(), ExtensionBackend), (
    "ToolBackend must satisfy the ExtensionBackend protocol"
)
