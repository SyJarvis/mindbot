"""Unit tests for CapabilityExecutor."""

from __future__ import annotations

import pytest

from mindbot.capability.executor import CapabilityExecutor
from mindbot.capability.models import (
    Capability,
    CapabilityConflictError,
    CapabilityExecutionError,
    CapabilityNotFoundError,
    CapabilityQuery,
    CapabilityType,
)

from tests.capability.conftest import MockBackend


# ---------------------------------------------------------------------------
# add_backend / routing
# ---------------------------------------------------------------------------


def test_add_backend_indexes_capabilities(sample_capability: Capability) -> None:
    executor = CapabilityExecutor()
    backend = MockBackend([sample_capability])
    executor.add_backend(backend)
    caps = executor.list_capabilities()
    assert any(c.id == "cap_a" for c in caps)


def test_add_backend_conflict_raises(sample_capability: Capability) -> None:
    executor = CapabilityExecutor()
    b1 = MockBackend([sample_capability])
    b2 = MockBackend([sample_capability])
    executor.add_backend(b1)
    with pytest.raises(CapabilityConflictError):
        executor.add_backend(b2)


def test_add_backend_conflict_replace(sample_capability: Capability) -> None:
    executor = CapabilityExecutor()
    b1 = MockBackend([sample_capability])
    b2 = MockBackend([sample_capability])
    executor.add_backend(b1)
    executor.add_backend(b2, replace=True)
    # Two distinct backends registered
    assert len(executor._backends) == 2  # noqa: SLF001


def test_remove_backend(sample_capability: Capability) -> None:
    executor = CapabilityExecutor()
    backend = MockBackend([sample_capability])
    executor.add_backend(backend)
    executor.remove_backend(backend)
    assert executor.list_capabilities() == []


def test_remove_unknown_backend_is_noop(sample_capability: Capability) -> None:
    executor = CapabilityExecutor()
    backend = MockBackend([sample_capability])
    executor.remove_backend(backend)  # should not raise


# ---------------------------------------------------------------------------
# execute – success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_success(sample_capability: Capability) -> None:
    executor = CapabilityExecutor()
    backend = MockBackend([sample_capability])
    executor.add_backend(backend)

    result = await executor.execute("cap_a", {"x": "hello"})

    assert result == "result:cap_a"
    assert backend.executed == [("cap_a", {"x": "hello"})]


@pytest.mark.asyncio
async def test_execute_passes_context(sample_capability: Capability) -> None:
    """Context forwarding: backend receives context dict."""
    received: list[dict] = []

    class ContextCapturingBackend:
        def type_id(self) -> str:
            return "tool"

        def list_capabilities(self) -> list[Capability]:
            return [sample_capability]

        async def execute(self, cap_id: str, args: dict, context: dict | None = None) -> str:
            received.append(context or {})
            return "ok"

    executor = CapabilityExecutor()
    executor.add_backend(ContextCapturingBackend())
    ctx = {"session_id": "abc"}
    await executor.execute("cap_a", {}, context=ctx)
    assert received == [ctx]


# ---------------------------------------------------------------------------
# execute – failure paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_unknown_capability_raises_not_found() -> None:
    executor = CapabilityExecutor()
    with pytest.raises(CapabilityNotFoundError):
        await executor.execute("nonexistent", {})


@pytest.mark.asyncio
async def test_execute_backend_exception_wraps_as_execution_error(
    sample_capability: Capability,
    mock_backend_failing: MockBackend,
) -> None:
    executor = CapabilityExecutor()
    executor.add_backend(mock_backend_failing)

    with pytest.raises(CapabilityExecutionError) as exc_info:
        await executor.execute("cap_a", {})

    assert exc_info.value.capability_id == "cap_a"
    assert exc_info.value.cause is not None
    assert "backend boom" in str(exc_info.value)


@pytest.mark.asyncio
async def test_execute_reraises_capability_not_found_from_backend(
    sample_capability: Capability,
) -> None:
    """CapabilityNotFoundError from backend is re-raised as-is (not double-wrapped)."""

    class MismatchBackend:
        def type_id(self) -> str:
            return "tool"

        def list_capabilities(self) -> list[Capability]:
            return [sample_capability]

        async def execute(self, cap_id: str, args: dict, context: dict | None = None) -> str:
            raise CapabilityNotFoundError(cap_id)

    executor = CapabilityExecutor()
    executor.add_backend(MismatchBackend())

    with pytest.raises(CapabilityNotFoundError):
        await executor.execute("cap_a", {})


# ---------------------------------------------------------------------------
# build_registry
# ---------------------------------------------------------------------------


def test_build_registry_reflects_current_backends(
    sample_capability: Capability,
    another_capability: Capability,
) -> None:
    executor = CapabilityExecutor()
    executor.add_backend(MockBackend([sample_capability]))
    executor.add_backend(MockBackend([another_capability]))

    registry = executor.build_registry()
    assert len(registry) == 2
    assert registry.get_by_id("cap_a") is not None
    assert registry.get_by_id("cap_b") is not None
