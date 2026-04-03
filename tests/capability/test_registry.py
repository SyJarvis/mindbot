"""Unit tests for CapabilityRegistry."""

from __future__ import annotations

import pytest

from mindbot.capability.models import (
    Capability,
    CapabilityConflictError,
    CapabilityNotFoundError,
    CapabilityQuery,
    CapabilityType,
)
from mindbot.capability.registry import CapabilityRegistry

from tests.capability.conftest import MockBackend


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_register_and_get_by_id(sample_capability: Capability) -> None:
    registry = CapabilityRegistry()
    registry.register(sample_capability)
    assert registry.get_by_id("cap_a") is sample_capability


def test_register_duplicate_raises(sample_capability: Capability) -> None:
    registry = CapabilityRegistry()
    registry.register(sample_capability)
    with pytest.raises(CapabilityConflictError) as exc_info:
        registry.register(sample_capability)
    assert "cap_a" in str(exc_info.value)


def test_register_duplicate_with_replace(sample_capability: Capability) -> None:
    registry = CapabilityRegistry()
    registry.register(sample_capability)
    new_cap = Capability(id="cap_a", name="CapabilityA-v2", description="updated")
    registry.register(new_cap, replace=True)
    assert registry.get_by_id("cap_a").name == "CapabilityA-v2"


def test_register_many(sample_capability: Capability, another_capability: Capability) -> None:
    registry = CapabilityRegistry()
    registry.register_many([sample_capability, another_capability])
    assert len(registry) == 2


def test_register_from_backend(sample_capability: Capability) -> None:
    registry = CapabilityRegistry()
    backend = MockBackend([sample_capability])
    registry.register_from_backend(backend)
    assert "cap_a" in registry


# ---------------------------------------------------------------------------
# list_all / __len__ / __contains__
# ---------------------------------------------------------------------------


def test_list_all_empty() -> None:
    assert CapabilityRegistry().list_all() == []


def test_list_all_populated(sample_capability: Capability, another_capability: Capability) -> None:
    registry = CapabilityRegistry.from_capabilities([sample_capability, another_capability])
    ids = {c.id for c in registry.list_all()}
    assert ids == {"cap_a", "cap_b"}


def test_contains(sample_capability: Capability) -> None:
    registry = CapabilityRegistry.from_capabilities([sample_capability])
    assert "cap_a" in registry
    assert "unknown" not in registry


# ---------------------------------------------------------------------------
# resolve – exact ID match
# ---------------------------------------------------------------------------


def test_resolve_by_exact_id(sample_capability: Capability) -> None:
    registry = CapabilityRegistry.from_capabilities([sample_capability])
    result = registry.resolve(CapabilityQuery(capability_id="cap_a"))
    assert result is sample_capability


def test_resolve_by_id_not_found() -> None:
    registry = CapabilityRegistry()
    with pytest.raises(CapabilityNotFoundError):
        registry.resolve(CapabilityQuery(capability_id="nonexistent"))


# ---------------------------------------------------------------------------
# resolve – exact name match
# ---------------------------------------------------------------------------


def test_resolve_by_name(sample_capability: Capability) -> None:
    registry = CapabilityRegistry.from_capabilities([sample_capability])
    result = registry.resolve(CapabilityQuery(name="CapabilityA"))
    assert result is sample_capability


def test_resolve_by_name_not_found() -> None:
    registry = CapabilityRegistry()
    with pytest.raises(CapabilityNotFoundError):
        registry.resolve(CapabilityQuery(name="NoSuchName"))


# ---------------------------------------------------------------------------
# resolve – type filter
# ---------------------------------------------------------------------------


def test_resolve_by_id_with_correct_type(sample_capability: Capability) -> None:
    registry = CapabilityRegistry.from_capabilities([sample_capability])
    result = registry.resolve(
        CapabilityQuery(capability_id="cap_a", capability_type=CapabilityType.TOOL)
    )
    assert result is sample_capability


def test_resolve_by_id_with_wrong_type(sample_capability: Capability) -> None:
    """ID matches but type filter excludes it → not found."""
    registry = CapabilityRegistry.from_capabilities([sample_capability])
    with pytest.raises(CapabilityNotFoundError):
        registry.resolve(
            CapabilityQuery(capability_id="cap_a", capability_type=CapabilityType.SKILL)
        )


# ---------------------------------------------------------------------------
# resolve – description hint
# ---------------------------------------------------------------------------


def test_resolve_by_description_hint(sample_capability: Capability) -> None:
    registry = CapabilityRegistry.from_capabilities([sample_capability])
    result = registry.resolve(CapabilityQuery(description_hint="useful for testing"))
    assert result is sample_capability


def test_resolve_by_description_hint_case_insensitive(sample_capability: Capability) -> None:
    registry = CapabilityRegistry.from_capabilities([sample_capability])
    result = registry.resolve(CapabilityQuery(description_hint="USEFUL FOR TESTING"))
    assert result is sample_capability


def test_resolve_by_description_hint_not_found() -> None:
    registry = CapabilityRegistry()
    with pytest.raises(CapabilityNotFoundError):
        registry.resolve(CapabilityQuery(description_hint="absolutely nothing"))


# ---------------------------------------------------------------------------
# CapabilityQuery validation
# ---------------------------------------------------------------------------


def test_query_requires_at_least_one_field() -> None:
    with pytest.raises(ValueError):
        CapabilityQuery()


def test_query_with_only_description_hint_is_valid() -> None:
    q = CapabilityQuery(description_hint="something")
    assert q.description_hint == "something"
