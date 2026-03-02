"""ToolDefinition – the data model for LLM-generated dynamic tools.

A :class:`ToolDefinition` is the persisted, validated representation of a
tool whose implementation is registered at runtime (as opposed to a
statically-coded :class:`~mindbot.capability.backends.tooling.models.Tool`).

Storage
-------
Definitions are stored as JSON files under ``~/.mindbot/tools/``.  Each file
contains a single serialised :class:`ToolDefinition`.

Execution
---------
The :class:`~mindbot.generation.executor.DynamicToolExecutor` resolves the
callable from :attr:`ToolDefinition.implementation_ref` and executes it with
the caller-supplied arguments.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# ImplementationType
# ---------------------------------------------------------------------------


class ImplementationType(str, Enum):
    """How the tool's implementation is referenced.

    Attributes:
        CALLABLE: A dotted Python import path (``"my_pkg.my_module.my_func"``).
            The executor will ``importlib.import_module`` the module and look
            up the attribute at runtime.
        MOCK: A simple echo/stub implementation used for testing and
            development.  Ignores *implementation_ref*.
    """

    CALLABLE = "callable"
    MOCK = "mock"


# ---------------------------------------------------------------------------
# ToolDefinition
# ---------------------------------------------------------------------------


@dataclass
class ToolDefinition:
    """Persisted, validated representation of a dynamically generated tool.

    Attributes:
        id: Globally unique identifier, used as the capability ID.
        name: Tool name exposed to the LLM (must be unique within the
            definition registry).
        description: Natural-language description forwarded to the LLM.
        parameters_schema: JSON Schema ``object`` for the tool's parameters.
        implementation_type: How the callable is resolved at execution time.
        implementation_ref: Reference to the callable (interpretation depends
            on *implementation_type*).  Empty string for ``MOCK`` types.
        version: Semantic-ish version string.
        created_at: Unix timestamp of first creation.
        updated_at: Unix timestamp of last update.
        metadata: Arbitrary key-value pairs for tooling / observability.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    parameters_schema: dict[str, Any] = field(default_factory=dict)
    implementation_type: ImplementationType = ImplementationType.MOCK
    implementation_ref: str = ""
    version: str = "1.0.0"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-compatible dict."""
        return {
            "schema_version": "1",
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "parameters_schema": self.parameters_schema,
            "implementation_type": self.implementation_type.value,
            "implementation_ref": self.implementation_ref,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolDefinition":
        """Deserialise from a JSON-compatible dict.

        ``id`` is optional – when absent a new UUID is generated so that raw
        LLM output (which rarely includes an ``id`` field) is accepted without
        error.
        """
        return cls(
            id=data.get("id") or str(uuid.uuid4()),
            name=data["name"],
            description=data["description"],
            parameters_schema=data.get("parameters_schema", {}),
            implementation_type=ImplementationType(data.get("implementation_type", "mock")),
            implementation_ref=data.get("implementation_ref", ""),
            version=data.get("version", "1.0.0"),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            metadata=data.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------


class ToolDefinitionError(Exception):
    """Base exception for ToolDefinition validation failures."""


class ToolDefinitionNotFoundError(ToolDefinitionError):
    """Raised when a ToolDefinition cannot be found by ID or name.

    Args:
        key: The ID or name that was looked up.
    """

    def __init__(self, key: str) -> None:
        super().__init__(f"ToolDefinition not found: '{key}'")
        self.key = key


class ToolDefinitionConflictError(ToolDefinitionError):
    """Raised when registering a ToolDefinition whose name already exists.

    Args:
        name: The conflicting tool name.
    """

    def __init__(self, name: str) -> None:
        super().__init__(
            f"ToolDefinition with name '{name}' already exists. "
            "Use update() to replace it."
        )
        self.name = name
