"""Tests for generation/registry.py – persistence and in-memory operations."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from mindbot.generation.models import (
    ImplementationType,
    ToolDefinition,
    ToolDefinitionConflictError,
    ToolDefinitionNotFoundError,
)
from mindbot.generation.registry import ToolDefinitionRegistry


# ---------------------------------------------------------------------------
# Fixture: temp directory for store
# ---------------------------------------------------------------------------


@pytest.fixture()
def store_dir(tmp_path: Path) -> Path:
    return tmp_path / "tools"


@pytest.fixture()
def registry(store_dir: Path) -> ToolDefinitionRegistry:
    return ToolDefinitionRegistry(store_dir=store_dir)


@pytest.fixture()
def sample_defn() -> ToolDefinition:
    return ToolDefinition(name="calc_add", description="Add two integers")


@pytest.fixture()
def another_defn() -> ToolDefinition:
    return ToolDefinition(name="search_web", description="Search the internet")


# ---------------------------------------------------------------------------
# save / get_by_id / get_by_name
# ---------------------------------------------------------------------------


def test_save_and_get_by_id(registry: ToolDefinitionRegistry, sample_defn: ToolDefinition) -> None:
    registry.save(sample_defn)
    result = registry.get_by_id(sample_defn.id)
    assert result is not None
    assert result.name == "calc_add"


def test_save_and_get_by_name(registry: ToolDefinitionRegistry, sample_defn: ToolDefinition) -> None:
    registry.save(sample_defn)
    result = registry.get_by_name("calc_add")
    assert result is not None
    assert result.id == sample_defn.id


def test_get_by_id_missing_returns_none(registry: ToolDefinitionRegistry) -> None:
    assert registry.get_by_id("nonexistent") is None


def test_get_by_name_missing_returns_none(registry: ToolDefinitionRegistry) -> None:
    assert registry.get_by_name("nonexistent") is None


# ---------------------------------------------------------------------------
# Conflict handling
# ---------------------------------------------------------------------------


def test_save_duplicate_name_raises(
    registry: ToolDefinitionRegistry,
    sample_defn: ToolDefinition,
) -> None:
    registry.save(sample_defn)
    duplicate = ToolDefinition(name="calc_add", description="Another version")
    with pytest.raises(ToolDefinitionConflictError):
        registry.save(duplicate)


def test_save_duplicate_with_replace(
    registry: ToolDefinitionRegistry,
    sample_defn: ToolDefinition,
) -> None:
    registry.save(sample_defn)
    replacement = ToolDefinition(name="calc_add", description="Updated version")
    registry.save(replacement, replace=True)
    assert registry.get_by_name("calc_add").description == "Updated version"


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


def test_update_existing(registry: ToolDefinitionRegistry, sample_defn: ToolDefinition) -> None:
    registry.save(sample_defn)
    sample_defn.description = "Updated description"
    registry.update(sample_defn)
    result = registry.get_by_id(sample_defn.id)
    assert result.description == "Updated description"


def test_update_nonexistent_raises(registry: ToolDefinitionRegistry) -> None:
    ghost = ToolDefinition(name="ghost", description="Not saved")
    with pytest.raises(ToolDefinitionNotFoundError):
        registry.update(ghost)


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


def test_delete_existing(registry: ToolDefinitionRegistry, sample_defn: ToolDefinition) -> None:
    registry.save(sample_defn)
    registry.delete(sample_defn.id)
    assert registry.get_by_id(sample_defn.id) is None


def test_delete_nonexistent_raises(registry: ToolDefinitionRegistry) -> None:
    with pytest.raises(ToolDefinitionNotFoundError):
        registry.delete("nonexistent-id")


# ---------------------------------------------------------------------------
# list_all / __len__ / __contains__
# ---------------------------------------------------------------------------


def test_list_all_empty(registry: ToolDefinitionRegistry) -> None:
    assert registry.list_all() == []


def test_list_all_multiple(
    registry: ToolDefinitionRegistry,
    sample_defn: ToolDefinition,
    another_defn: ToolDefinition,
) -> None:
    registry.save(sample_defn)
    registry.save(another_defn)
    names = {d.name for d in registry.list_all()}
    assert names == {"calc_add", "search_web"}


def test_len_and_contains(registry: ToolDefinitionRegistry, sample_defn: ToolDefinition) -> None:
    assert len(registry) == 0
    registry.save(sample_defn)
    assert len(registry) == 1
    assert sample_defn.id in registry


# ---------------------------------------------------------------------------
# Persistence – load_all (restart simulation)
# ---------------------------------------------------------------------------


def test_load_all_restores_definitions(
    store_dir: Path,
    sample_defn: ToolDefinition,
    another_defn: ToolDefinition,
) -> None:
    # Save definitions using a first registry instance
    registry1 = ToolDefinitionRegistry(store_dir=store_dir)
    registry1.save(sample_defn)
    registry1.save(another_defn)

    # Create a fresh registry and load from disk
    registry2 = ToolDefinitionRegistry(store_dir=store_dir)
    count = registry2.load_all()

    assert count == 2
    assert registry2.get_by_name("calc_add") is not None
    assert registry2.get_by_name("search_web") is not None


def test_load_all_empty_dir_returns_zero(tmp_path: Path) -> None:
    registry = ToolDefinitionRegistry(store_dir=tmp_path / "empty")
    assert registry.load_all() == 0


def test_file_is_written_to_disk(store_dir: Path, sample_defn: ToolDefinition) -> None:
    registry = ToolDefinitionRegistry(store_dir=store_dir)
    registry.save(sample_defn)
    expected_file = store_dir / "calc_add.json"
    assert expected_file.exists()


def test_delete_removes_file(store_dir: Path, sample_defn: ToolDefinition) -> None:
    registry = ToolDefinitionRegistry(store_dir=store_dir)
    registry.save(sample_defn)
    registry.delete(sample_defn.id)
    expected_file = store_dir / "calc_add.json"
    assert not expected_file.exists()
