"""Capability layer – core data models.

These types form the frozen contract between the orchestration layer and
any concrete execution backend (Tool, Skill, MCP, …).  Upper-layer code
must depend *only* on these models; it must never import backend-specific
types directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# CapabilityType
# ---------------------------------------------------------------------------


class CapabilityType(str, Enum):
    """The carrier type that backs a capability."""

    TOOL = "tool"
    SKILL = "skill"
    MCP = "mcp"


# ---------------------------------------------------------------------------
# Capability
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Capability:
    """Unified description of a single executable capability.

    This is the only representation the orchestration layer needs.  Backend
    details (e.g. a concrete Python handler or an MCP server address) live
    inside the :class:`~mindbot.capability.backends.base.ExtensionBackend`
    that registered this capability.

    Attributes:
        id: Globally unique capability identifier (e.g. ``"read_word_doc"``).
        name: Human-readable display name.
        description: Natural-language description exposed to the LLM and the
            routing/resolve logic.
        parameters_schema: JSON Schema ``object`` describing accepted
            arguments.  Aligned with the existing ``Tool.parameters_json_schema``
            format so it can be forwarded to the LLM unchanged.
        capability_type: Carrier type – used for routing when the executor
            needs to select the right backend.
        backend_id: Identifier of the capability *within* the backend (e.g.
            the tool name in the tool registry, or ``"server/tool"`` for MCP).
    """

    id: str
    name: str
    description: str
    parameters_schema: dict[str, Any] = field(default_factory=dict)
    capability_type: CapabilityType = CapabilityType.TOOL
    backend_id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Capability.id must not be empty")
        if not self.name:
            raise ValueError("Capability.name must not be empty")
        # backend_id defaults to id when not provided
        if not self.backend_id:
            object.__setattr__(self, "backend_id", self.id)


# ---------------------------------------------------------------------------
# CapabilityQuery
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CapabilityQuery:
    """Parameters used to look up a capability in the registry.

    At least one of ``capability_id`` or ``name`` must be provided.

    Attributes:
        capability_id: Exact capability ID to look up.
        name: Exact name to look up (secondary lookup after ID).
        description_hint: Free-text hint used for fuzzy description matching
            when exact ID/name lookup yields no result.
        capability_type: Optionally restrict the search to a specific backend
            type.
    """

    capability_id: str | None = None
    name: str | None = None
    description_hint: str | None = None
    capability_type: CapabilityType | None = None

    def __post_init__(self) -> None:
        if not any([self.capability_id, self.name, self.description_hint]):
            raise ValueError(
                "CapabilityQuery requires at least one of: "
                "capability_id, name, or description_hint"
            )


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------


class CapabilityError(Exception):
    """Base exception for all capability-layer errors."""


class CapabilityNotFoundError(CapabilityError):
    """Raised when a capability cannot be found in the registry.

    Args:
        query: The query that produced no result.
    """

    def __init__(self, query: CapabilityQuery | str) -> None:
        detail = str(query)
        super().__init__(f"Capability not found: {detail}")
        self.query = query


class CapabilityConflictError(CapabilityError):
    """Raised when registering a capability whose ID already exists.

    Args:
        capability_id: The conflicting ID.
    """

    def __init__(self, capability_id: str) -> None:
        super().__init__(
            f"Capability '{capability_id}' is already registered. "
            "Use replace=True to override."
        )
        self.capability_id = capability_id


class CapabilityExecutionError(CapabilityError):
    """Raised when a backend fails during capability execution.

    Args:
        capability_id: The capability that was being executed.
        cause: The underlying exception, if any.
    """

    def __init__(self, capability_id: str, cause: BaseException | None = None) -> None:
        msg = f"Execution failed for capability '{capability_id}'"
        if cause is not None:
            msg = f"{msg}: {type(cause).__name__}: {cause}"
        super().__init__(msg)
        self.capability_id = capability_id
        self.cause = cause
