"""Unit tests for CapabilityFacade – the primary upper-layer API."""

from __future__ import annotations

import pytest

from mindbot.capability.facade import CapabilityFacade
from mindbot.capability.models import (
    Capability,
    CapabilityExecutionError,
    CapabilityNotFoundError,
    CapabilityQuery,
    CapabilityType,
)

from tests.capability.conftest import MockBackend


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _facade_with_backend(backend: MockBackend) -> CapabilityFacade:
    facade = CapabilityFacade()
    facade.add_backend(backend)
    return facade


# ---------------------------------------------------------------------------
# resolve
# ---------------------------------------------------------------------------


def test_resolve_by_id(sample_capability: Capability) -> None:
    facade = _facade_with_backend(MockBackend([sample_capability]))
    cap = facade.resolve(CapabilityQuery(capability_id="cap_a"))
    assert cap.id == "cap_a"


def test_resolve_not_found_raises(sample_capability: Capability) -> None:
    facade = _facade_with_backend(MockBackend([sample_capability]))
    with pytest.raises(CapabilityNotFoundError):
        facade.resolve(CapabilityQuery(capability_id="missing"))


def test_resolve_by_name(sample_capability: Capability) -> None:
    facade = _facade_with_backend(MockBackend([sample_capability]))
    cap = facade.resolve(CapabilityQuery(name="CapabilityA"))
    assert cap.name == "CapabilityA"


def test_resolve_by_description_hint(sample_capability: Capability) -> None:
    facade = _facade_with_backend(MockBackend([sample_capability]))
    cap = facade.resolve(CapabilityQuery(description_hint="useful for testing"))
    assert cap.id == "cap_a"


# ---------------------------------------------------------------------------
# execute
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_success(sample_capability: Capability) -> None:
    backend = MockBackend([sample_capability])
    facade = _facade_with_backend(backend)

    result = await facade.execute("cap_a", {"x": "v"})

    assert result == "result:cap_a"
    assert backend.executed == [("cap_a", {"x": "v"})]


@pytest.mark.asyncio
async def test_execute_unknown_id_raises_not_found() -> None:
    facade = CapabilityFacade()
    with pytest.raises(CapabilityNotFoundError):
        await facade.execute("no_such_cap", {})


@pytest.mark.asyncio
async def test_execute_backend_error_raises_execution_error(
    sample_capability: Capability,
    mock_backend_failing: MockBackend,
) -> None:
    facade = _facade_with_backend(mock_backend_failing)
    with pytest.raises(CapabilityExecutionError) as exc_info:
        await facade.execute("cap_a", {})
    assert "cap_a" in str(exc_info.value)


# ---------------------------------------------------------------------------
# resolve_and_execute (combined)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_and_execute_success(sample_capability: Capability) -> None:
    backend = MockBackend([sample_capability])
    facade = _facade_with_backend(backend)

    result = await facade.resolve_and_execute(
        CapabilityQuery(capability_id="cap_a"),
        arguments={"x": "hello"},
    )

    assert result == "result:cap_a"
    assert backend.executed == [("cap_a", {"x": "hello"})]


@pytest.mark.asyncio
async def test_resolve_and_execute_missing_raises(sample_capability: Capability) -> None:
    facade = _facade_with_backend(MockBackend([sample_capability]))
    with pytest.raises(CapabilityNotFoundError):
        await facade.resolve_and_execute(
            CapabilityQuery(capability_id="missing_cap"),
            arguments={},
        )


@pytest.mark.asyncio
async def test_resolve_and_execute_backend_failure_raises(
    sample_capability: Capability,
    mock_backend_failing: MockBackend,
) -> None:
    facade = _facade_with_backend(mock_backend_failing)
    with pytest.raises(CapabilityExecutionError):
        await facade.resolve_and_execute(
            CapabilityQuery(capability_id="cap_a"),
            arguments={},
        )


# ---------------------------------------------------------------------------
# list_capabilities
# ---------------------------------------------------------------------------


def test_list_capabilities_empty() -> None:
    assert CapabilityFacade().list_capabilities() == []


def test_list_capabilities_from_backend(
    sample_capability: Capability,
    another_capability: Capability,
) -> None:
    facade = CapabilityFacade()
    facade.add_backend(MockBackend([sample_capability, another_capability]))
    ids = {c.id for c in facade.list_capabilities()}
    assert ids == {"cap_a", "cap_b"}


# ---------------------------------------------------------------------------
# remove_backend / refresh_registry
# ---------------------------------------------------------------------------


def test_remove_backend_stops_execution(sample_capability: Capability) -> None:
    backend = MockBackend([sample_capability])
    facade = _facade_with_backend(backend)
    facade.remove_backend(backend)
    # After removal the executor routing is gone
    import asyncio
    with pytest.raises(CapabilityNotFoundError):
        asyncio.get_event_loop().run_until_complete(facade.execute("cap_a", {}))


def test_refresh_registry_after_dynamic_change(sample_capability: Capability) -> None:
    """After adding more capabilities to a mutable backend, refresh_registry
    makes them visible through resolve."""
    backend = MockBackend([sample_capability])
    facade = _facade_with_backend(backend)

    new_cap = Capability(id="cap_new", name="NewCap", description="dynamically added")
    backend._capabilities.append(new_cap)

    facade.refresh_registry()

    cap = facade.resolve(CapabilityQuery(capability_id="cap_new"))
    assert cap.id == "cap_new"


# ---------------------------------------------------------------------------
# Multiple backends
# ---------------------------------------------------------------------------


def test_two_backends_no_conflict(
    sample_capability: Capability,
    another_capability: Capability,
) -> None:
    facade = CapabilityFacade()
    facade.add_backend(MockBackend([sample_capability]))
    facade.add_backend(MockBackend([another_capability]))
    assert len(facade.list_capabilities()) == 2


@pytest.mark.asyncio
async def test_execute_routes_to_correct_backend(
    sample_capability: Capability,
    another_capability: Capability,
) -> None:
    b1 = MockBackend([sample_capability])
    b2 = MockBackend([another_capability])
    facade = CapabilityFacade()
    facade.add_backend(b1)
    facade.add_backend(b2)

    await facade.execute("cap_a", {})
    await facade.execute("cap_b", {})

    assert b1.executed == [("cap_a", {})]
    assert b2.executed == [("cap_b", {})]
