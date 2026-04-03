"""Capability facade – the single entry point for upper-layer code.

Upper-layer modules (legacy orchestrators, application services, etc.)
must depend **only** on :class:`CapabilityFacade` and the types in
:mod:`~mindbot.capability.models`.  They must never import concrete backends
or the registry/executor directly.

Typical usage::

    from mindbot.capability import CapabilityFacade
    from mindbot.capability.models import CapabilityQuery

    facade = CapabilityFacade()
    facade.add_backend(my_tool_backend)

    # Resolve then execute (two steps)
    cap = facade.resolve(CapabilityQuery(name="web_search"))
    result = await facade.execute(cap.id, {"query": "hello world"})

    # Or combine into one call
    result = await facade.resolve_and_execute(
        CapabilityQuery(name="web_search"),
        arguments={"query": "hello world"},
    )
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mindbot.capability.backends.base import ExtensionBackend
from mindbot.capability.executor import CapabilityExecutor
from mindbot.capability.models import (
    Capability,
    CapabilityNotFoundError,
    CapabilityQuery,
    CapabilityType,
)
from mindbot.capability.registry import CapabilityRegistry
from mindbot.utils import get_logger

if TYPE_CHECKING:
    from mindbot.capability.backends.tooling.models import Tool

logger = get_logger("capability.facade")


class CapabilityFacade:
    """Unified capability API for upper-layer consumers.

    Combines :class:`~mindbot.capability.registry.CapabilityRegistry`
    (resolve) and :class:`~mindbot.capability.executor.CapabilityExecutor`
    (execute) behind a single coherent interface.

    Backends are registered once via :meth:`add_backend`; the facade
    keeps the registry and executor in sync automatically.
    """

    def __init__(self) -> None:
        self._executor = CapabilityExecutor()
        self._registry = CapabilityRegistry()

    # ------------------------------------------------------------------
    # Backend wiring
    # ------------------------------------------------------------------

    def add_backend(self, backend: ExtensionBackend, *, replace: bool = False) -> None:
        """Register an :class:`~mindbot.capability.backends.base.ExtensionBackend`.

        The backend's capabilities are indexed in both the registry and the
        executor routing table.

        Args:
            backend: The backend to register.
            replace: Forward to both registry and executor; allows replacing
                capabilities with the same ID.
        """
        self._executor.add_backend(backend, replace=replace)
        self._registry.register_from_backend(backend, replace=replace)

    def remove_backend(self, backend: ExtensionBackend) -> None:
        """Remove a backend.

        Capabilities owned by this backend are removed from the executor
        routing table.  Note: the registry is *not* updated retroactively
        (stale entries remain but become un-executable).  A future
        ``refresh_registry()`` call rebuilds the registry from live backends.
        """
        self._executor.remove_backend(backend)

    def refresh_registry(self) -> None:
        """Rebuild the registry and executor routing from all registered backends.

        Call this after adding/removing dynamic capabilities at runtime (e.g.
        after a new tool is generated).  Both the resolve index
        (:class:`~mindbot.capability.registry.CapabilityRegistry`) and the
        execution routing table (:class:`~mindbot.capability.executor.CapabilityExecutor`)
        are rebuilt from the current live state of every backend.
        """
        self._executor.rebuild_routing()
        self._registry = self._executor.build_registry()

    # ------------------------------------------------------------------
    # Resolve
    # ------------------------------------------------------------------

    def resolve(self, query: CapabilityQuery) -> Capability:
        """Look up a capability matching *query*.

        Args:
            query: Lookup parameters (ID, name, description hint, type).

        Returns:
            The matching :class:`~mindbot.capability.models.Capability`.

        Raises:
            CapabilityNotFoundError: When no capability satisfies the query.
        """
        return self._registry.resolve(query)

    def list_capabilities(self) -> list[Capability]:
        """Return all capabilities currently available through this facade."""
        return self._registry.list_all()

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    async def execute(
        self,
        capability_id: str,
        arguments: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> str:
        """Execute a capability by ID.

        Args:
            capability_id: The globally unique capability ID.
            arguments: Call arguments.
            context: Optional session / step context.

        Returns:
            String result from the backend.

        Raises:
            CapabilityNotFoundError: When *capability_id* is unknown.
            CapabilityExecutionError: When the backend raises at runtime.
        """
        return await self._executor.execute(capability_id, arguments, context)

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    async def resolve_and_execute(
        self,
        query: CapabilityQuery,
        arguments: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> str:
        """Resolve a query and immediately execute the result.

        This is the most common pattern for the orchestration layer:

        1. Resolve the capability matching *query*.
        2. Execute it with *arguments*.

        Args:
            query: Lookup parameters.
            arguments: Call arguments.
            context: Optional session / step context.

        Returns:
            String result from the backend.

        Raises:
            CapabilityNotFoundError: When no capability matches *query*.
            CapabilityExecutionError: When the backend raises at runtime.
        """
        cap = self.resolve(query)
        logger.debug("Resolved '%s' for query %s", cap.id, query)
        return await self.execute(cap.id, arguments, context)


class ScopedCapabilityFacade:
    """Turn-scoped capability view layered on top of a base facade.

    Overlay backends are resolved and executed before the base facade. This lets
    a single turn expose a temporary capability set without mutating the global
    registry. Optionally, specific capability types can be shadowed from the
    base facade entirely.
    """

    def __init__(
        self,
        base_facade: CapabilityFacade | None = None,
        *,
        shadow_base_types: set[CapabilityType] | None = None,
    ) -> None:
        self._base_facade = base_facade
        self._overlay_executor = CapabilityExecutor()
        self._overlay_registry = CapabilityRegistry()
        self._shadow_base_types = set(shadow_base_types or set())

    def add_overlay_backend(self, backend: ExtensionBackend, *, replace: bool = True) -> None:
        """Register a turn-scoped backend visible only through this view."""
        self._overlay_executor.add_backend(backend, replace=replace)
        self._overlay_registry.register_from_backend(backend, replace=replace)

    def _overlay_capabilities(self) -> list[Capability]:
        return self._overlay_registry.list_all()

    def _is_shadowed_capability(self, capability: Capability) -> bool:
        return capability.capability_type in self._shadow_base_types

    def _query_targets_shadowed_type(self, query: CapabilityQuery) -> bool:
        return query.capability_type in self._shadow_base_types

    def resolve(self, query: CapabilityQuery) -> Capability:
        """Resolve against overlay backends first, then the base facade."""
        overlay_exc: CapabilityNotFoundError | None = None
        try:
            return self._overlay_registry.resolve(query)
        except CapabilityNotFoundError as exc:
            overlay_exc = exc

        if self._query_targets_shadowed_type(query):
            raise overlay_exc or CapabilityNotFoundError(query)

        if self._base_facade is None:
            raise overlay_exc or CapabilityNotFoundError(query)

        capability = self._base_facade.resolve(query)
        if self._is_shadowed_capability(capability):
            raise overlay_exc or CapabilityNotFoundError(query)
        return capability

    def list_capabilities(self) -> list[Capability]:
        """Return overlay capabilities first, then unshadowed base capabilities."""
        overlay_caps = self._overlay_capabilities()
        result = list(overlay_caps)
        seen_ids = {cap.id for cap in overlay_caps}
        seen_names = {cap.name for cap in overlay_caps}

        if self._base_facade is None:
            return result

        for cap in self._base_facade.list_capabilities():
            if cap.id in seen_ids or cap.name in seen_names:
                continue
            if self._is_shadowed_capability(cap):
                continue
            result.append(cap)
        return result

    async def execute(
        self,
        capability_id: str,
        arguments: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> str:
        """Execute using overlay backends first, then the base facade."""
        try:
            return await self._overlay_executor.execute(capability_id, arguments, context)
        except CapabilityNotFoundError:
            pass

        if self._base_facade is None:
            raise CapabilityNotFoundError(CapabilityQuery(capability_id=capability_id))

        capability = self._base_facade.resolve(CapabilityQuery(capability_id=capability_id))
        if self._is_shadowed_capability(capability):
            raise CapabilityNotFoundError(CapabilityQuery(capability_id=capability_id))
        return await self._base_facade.execute(capability_id, arguments, context)

    async def resolve_and_execute(
        self,
        query: CapabilityQuery,
        arguments: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> str:
        """Resolve against this scoped view, then execute on the owning backend."""
        capability = self.resolve(query)
        logger.debug("Resolved '%s' for scoped query %s", capability.id, query)

        overlay_cap = self._overlay_registry.get_by_id(capability.id)
        if overlay_cap is not None:
            return await self._overlay_executor.execute(capability.id, arguments, context)
        return await self.execute(capability.id, arguments, context)


def build_turn_scoped_facade(
    base_facade: CapabilityFacade | None,
    tools: list["Tool"] | None,
    *,
    override_tool_capabilities: bool,
) -> CapabilityFacade | ScopedCapabilityFacade | None:
    """Build the capability view used for a single turn.

    Args:
        base_facade: The long-lived facade owned by the agent, if any.
        tools: Tools visible for the current turn.
        override_tool_capabilities: When true, base tool capabilities are
            hidden for this turn so the supplied *tools* fully replace the
            registered tool set.
    """
    if not tools and not override_tool_capabilities:
        return base_facade

    from mindbot.capability.backends.tool_backend import ToolBackend
    from mindbot.capability.backends.tooling.registry import ToolRegistry

    scoped = ScopedCapabilityFacade(
        base_facade,
        shadow_base_types={CapabilityType.TOOL} if override_tool_capabilities else None,
    )
    if tools:
        scoped.add_overlay_backend(
            ToolBackend(static_registry=ToolRegistry.from_tools(tools)),
            replace=True,
        )
    return scoped
