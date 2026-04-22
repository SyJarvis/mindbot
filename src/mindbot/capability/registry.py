"""Capability registry – stores, resolves, and manages capabilities.

The registry is the single source of truth for what capabilities are
currently available.  It can be populated manually (``register``) or by
aggregating capabilities from one or more
:class:`~mindbot.capability.backends.base.ExtensionBackend` instances
(``register_from_backend``).
"""

from __future__ import annotations

from typing import Iterable

from mindbot.capability.models import (
    Capability,
    CapabilityConflictError,
    CapabilityNotFoundError,
    CapabilityQuery,
)
from mindbot.utils import get_logger

logger = get_logger("capability.registry")


class CapabilityRegistry:
    """Instance-based capability registry.

    Each agent / context can have its own independent registry.

    Resolution order in :meth:`resolve`:
    1. Exact ``capability_id`` match.
    2. Exact ``name`` match.
    3. ``capability_type`` filter (when set in the query).
    4. ``description_hint`` substring match (case-insensitive).

    Conflict policy: by default re-registering the same ``id`` raises
    :exc:`~mindbot.capability.models.CapabilityConflictError`.  Pass
    ``replace=True`` to silently overwrite.
    """

    def __init__(self) -> None:
        self._by_id: dict[str, Capability] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, capability: Capability, *, replace: bool = False) -> None:
        """Register a single capability.

        Args:
            capability: The capability to register.
            replace: If *True*, an existing capability with the same ID is
                silently replaced.  If *False* (default) a
                :exc:`~mindbot.capability.models.CapabilityConflictError` is
                raised on duplicate IDs.

        Raises:
            CapabilityConflictError: When *replace* is *False* and a
                capability with the same ID already exists.
        """
        if capability.id in self._by_id and not replace:
            raise CapabilityConflictError(capability.id)
        self._by_id[capability.id] = capability
        logger.debug("Registered capability '%s' (type=%s)", capability.id, capability.capability_type)

    def register_many(
        self,
        capabilities: Iterable[Capability],
        *,
        replace: bool = False,
    ) -> None:
        """Register multiple capabilities at once.

        Args:
            capabilities: Iterable of capabilities to register.
            replace: Forwarded to :meth:`register` for each item.
        """
        for cap in capabilities:
            self.register(cap, replace=replace)

    def register_from_backend(self, backend: object, *, replace: bool = False) -> None:
        """Pull capabilities from a backend and register them all.

        The *backend* argument is intentionally typed as ``object`` here so
        that this module does not import the ``ExtensionBackend`` Protocol
        at runtime (avoiding a circular dependency when backends import from
        ``models``).  At runtime the object must satisfy the
        :class:`~mindbot.capability.backends.base.ExtensionBackend` protocol.

        Args:
            backend: An object that implements ``list_capabilities()``.
            replace: Forwarded to :meth:`register_many`.
        """
        capabilities = backend.list_capabilities()  # type: ignore[attr-defined]
        self.register_many(capabilities, replace=replace)
        logger.debug(
            "Registered %d capabilities from backend '%s'",
            len(capabilities),
            getattr(backend, "type_id", lambda: "<unknown>")(),
        )

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_by_id(self, capability_id: str) -> Capability | None:
        """Return the capability with the given ID, or *None*."""
        return self._by_id.get(capability_id)

    def list_all(self) -> list[Capability]:
        """Return all registered capabilities."""
        return list(self._by_id.values())

    def resolve(self, query: CapabilityQuery) -> Capability:
        """Resolve a query to a capability.

        Resolution order:
        1. Exact ID match (``query.capability_id``).
        2. Exact name match (``query.name``), optionally filtered by type.
        3. Description substring match (``query.description_hint``), optionally
           filtered by type.

        Args:
            query: The lookup parameters.

        Returns:
            The matching :class:`~mindbot.capability.models.Capability`.

        Raises:
            CapabilityNotFoundError: When no capability satisfies the query.
        """
        # 1. Exact ID lookup
        if query.capability_id:
            cap = self._by_id.get(query.capability_id)
            if cap is not None:
                if query.capability_type is None or cap.capability_type == query.capability_type:
                    return cap

        candidates = list(self._by_id.values())

        # Apply type filter early so later steps work on a smaller set
        if query.capability_type is not None:
            candidates = [c for c in candidates if c.capability_type == query.capability_type]

        # 2. Exact name match
        if query.name:
            by_name = [c for c in candidates if c.name == query.name]
            if len(by_name) == 1:
                return by_name[0]
            if len(by_name) > 1:
                # Multiple matches – return the first but log a warning
                logger.warning(
                    "Multiple capabilities match name '%s'; returning first.", query.name
                )
                return by_name[0]

        # 3. Description hint (case-insensitive substring)
        if query.description_hint:
            hint = query.description_hint.lower()
            by_desc = [c for c in candidates if hint in c.description.lower()]
            if len(by_desc) == 1:
                return by_desc[0]
            if len(by_desc) > 1:
                logger.warning(
                    "Multiple capabilities match description hint '%s'; returning first.",
                    query.description_hint,
                )
                return by_desc[0]

        raise CapabilityNotFoundError(query)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._by_id)

    def __contains__(self, capability_id: str) -> bool:
        return capability_id in self._by_id

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_capabilities(
        cls,
        capabilities: Iterable[Capability],
        *,
        replace: bool = False,
    ) -> "CapabilityRegistry":
        """Create a registry pre-populated with *capabilities*."""
        registry = cls()
        registry.register_many(capabilities, replace=replace)
        return registry
