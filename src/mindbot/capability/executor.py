"""Capability executor – routes execution to the correct backend.

The executor maintains a mapping of ``capability_id -> ExtensionBackend``
and delegates ``execute`` calls accordingly.  It never contains execution
logic itself; all logic lives in the backends.
"""

from __future__ import annotations

from typing import Any

from src.mindbot.capability.backends.base import ExtensionBackend
from src.mindbot.capability.models import (
    Capability,
    CapabilityExecutionError,
    CapabilityNotFoundError,
    CapabilityQuery,
)
from src.mindbot.capability.registry import CapabilityRegistry
from src.mindbot.utils import get_logger

logger = get_logger("capability.executor")


class CapabilityExecutor:
    """Routes capability execution to the registered backend.

    Usage::

        executor = CapabilityExecutor()
        executor.add_backend(my_tool_backend)
        result = await executor.execute("my_cap_id", {"arg": "value"})

    The executor keeps its own internal
    :class:`~mindbot.capability.registry.CapabilityRegistry` derived from all
    registered backends.  Callers that need registry-level queries (e.g.
    resolve-before-execute) should use
    :class:`~mindbot.capability.facade.CapabilityFacade` instead.
    """

    def __init__(self) -> None:
        self._backends: list[ExtensionBackend] = []
        # capability_id -> backend that owns it
        self._routing: dict[str, ExtensionBackend] = {}

    # ------------------------------------------------------------------
    # Backend management
    # ------------------------------------------------------------------

    def add_backend(self, backend: ExtensionBackend, *, replace: bool = False) -> None:
        """Register a backend and index its current capabilities.

        Args:
            backend: The backend to add.
            replace: If *True*, capabilities from this backend overwrite
                existing routing entries with the same ID.  If *False*
                (default) a :exc:`~mindbot.capability.models.CapabilityConflictError`
                is raised on ID conflicts.
        """
        from src.mindbot.capability.models import CapabilityConflictError

        capabilities = backend.list_capabilities()
        for cap in capabilities:
            if cap.id in self._routing and not replace:
                raise CapabilityConflictError(cap.id)
            self._routing[cap.id] = backend

        if backend not in self._backends:
            self._backends.append(backend)

        logger.debug(
            "Added backend '%s' exposing %d capabilities",
            backend.type_id(),
            len(capabilities),
        )

    def remove_backend(self, backend: ExtensionBackend) -> None:
        """Unregister a backend and remove its capabilities from the routing table."""
        if backend not in self._backends:
            return
        self._backends.remove(backend)
        # Remove all routing entries that point to this backend
        stale = [cid for cid, b in self._routing.items() if b is backend]
        for cid in stale:
            del self._routing[cid]
        logger.debug("Removed backend '%s'", backend.type_id())

    def list_capabilities(self) -> list[Capability]:
        """Return all capabilities currently routable by this executor."""
        seen: set[str] = set()
        result: list[Capability] = []
        for backend in self._backends:
            for cap in backend.list_capabilities():
                if cap.id not in seen:
                    seen.add(cap.id)
                    result.append(cap)
        return result

    def rebuild_routing(self) -> None:
        """Rebuild the capability → backend routing table from live backends.

        Re-queries every registered backend for its current
        :meth:`list_capabilities` output and replaces the existing routing
        table.  Call this (via
        :meth:`~mindbot.capability.facade.CapabilityFacade.refresh_registry`)
        after dynamic capabilities are added or removed at runtime.
        """
        new_routing: dict[str, ExtensionBackend] = {}
        for backend in self._backends:
            for cap in backend.list_capabilities():
                new_routing[cap.id] = backend
        self._routing = new_routing
        logger.debug("Routing table rebuilt: %d entries", len(self._routing))

    def build_registry(self) -> CapabilityRegistry:
        """Build a :class:`~mindbot.capability.registry.CapabilityRegistry`
        from all currently registered backends.

        Useful when callers need resolve-before-execute semantics.
        """
        return CapabilityRegistry.from_capabilities(self.list_capabilities())

    # ------------------------------------------------------------------
    # Execution
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
            arguments: Arguments to pass to the backend.
            context: Optional session / step context.

        Returns:
            String result from the backend, suitable for passing back to
            the LLM.

        Raises:
            CapabilityNotFoundError: When no backend handles *capability_id*.
            CapabilityExecutionError: When the backend raises an exception
                during execution.
        """
        backend = self._routing.get(capability_id)
        if backend is None:
            raise CapabilityNotFoundError(
                CapabilityQuery(capability_id=capability_id)
            )

        try:
            result = await backend.execute(capability_id, arguments, context)
            logger.debug("Executed capability '%s' successfully", capability_id)
            return result
        except (CapabilityNotFoundError, CapabilityExecutionError):
            raise
        except Exception as exc:
            logger.exception("Backend error while executing capability '%s'", capability_id)
            raise CapabilityExecutionError(capability_id, cause=exc) from exc
