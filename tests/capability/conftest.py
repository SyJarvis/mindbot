"""Shared fixtures for capability layer tests."""

from __future__ import annotations

from typing import Any

import pytest

from mindbot.capability.backends.base import ExtensionBackend
from mindbot.capability.models import (
    Capability,
    CapabilityExecutionError,
    CapabilityNotFoundError,
    CapabilityType,
)


# ---------------------------------------------------------------------------
# Minimal mock backend that satisfies ExtensionBackend protocol
# ---------------------------------------------------------------------------


class MockBackend:
    """A deterministic in-memory backend used only in tests."""

    def __init__(
        self,
        capabilities: list[Capability],
        *,
        backend_type: str = "tool",
        raise_on_execute: Exception | None = None,
    ) -> None:
        self._capabilities = capabilities
        self._backend_type = backend_type
        self._raise_on_execute = raise_on_execute
        self.executed: list[tuple[str, dict[str, Any]]] = []

    def type_id(self) -> str:
        return self._backend_type

    def list_capabilities(self) -> list[Capability]:
        return list(self._capabilities)

    async def execute(
        self,
        capability_id: str,
        arguments: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> str:
        if self._raise_on_execute is not None:
            raise self._raise_on_execute
        cap_ids = {c.id for c in self._capabilities}
        if capability_id not in cap_ids:
            raise CapabilityNotFoundError(capability_id)
        self.executed.append((capability_id, arguments))
        return f"result:{capability_id}"


assert isinstance(MockBackend([], backend_type="tool"), ExtensionBackend), (
    "MockBackend must satisfy the ExtensionBackend protocol"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_capability() -> Capability:
    return Capability(
        id="cap_a",
        name="CapabilityA",
        description="Does something useful for testing",
        parameters_schema={"type": "object", "properties": {"x": {"type": "string"}}},
        capability_type=CapabilityType.TOOL,
    )


@pytest.fixture()
def another_capability() -> Capability:
    return Capability(
        id="cap_b",
        name="CapabilityB",
        description="Another capability for testing",
        capability_type=CapabilityType.SKILL,
    )


@pytest.fixture()
def mock_backend(sample_capability: Capability) -> MockBackend:
    return MockBackend([sample_capability])


@pytest.fixture()
def mock_backend_failing(sample_capability: Capability) -> MockBackend:
    return MockBackend(
        [sample_capability],
        raise_on_execute=RuntimeError("backend boom"),
    )
