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

from typing import Any

from src.mindbot.capability.backends.base import ExtensionBackend
from src.mindbot.capability.executor import CapabilityExecutor
from src.mindbot.capability.models import (
    Capability,
    CapabilityNotFoundError,
    CapabilityQuery,
)
from src.mindbot.capability.registry import CapabilityRegistry
from src.mindbot.utils import get_logger

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
