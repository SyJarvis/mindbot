"""Tests for generation/models.py – ToolDefinition and errors."""

from __future__ import annotations

import pytest

from mindbot.generation.models import (
    ImplementationType,
    ToolDefinition,
    ToolDefinitionConflictError,
    ToolDefinitionNotFoundError,
)


def test_tool_definition_defaults() -> None:
    defn = ToolDefinition(name="my_tool", description="Does something")
    assert defn.implementation_type == ImplementationType.MOCK
    assert defn.implementation_ref == ""
    assert defn.version == "1.0.0"
    assert defn.id  # auto-generated UUID


def test_tool_definition_roundtrip() -> None:
    defn = ToolDefinition(
        name="add",
        description="Add two numbers",
        parameters_schema={
            "type": "object",
            "properties": {
                "a": {"type": "integer"},
                "b": {"type": "integer"},
            },
            "required": ["a", "b"],
        },
        implementation_type=ImplementationType.CALLABLE,
        implementation_ref="math.fsum",
    )
    data = defn.to_dict()
    restored = ToolDefinition.from_dict(data)

    assert restored.id == defn.id
    assert restored.name == defn.name
    assert restored.description == defn.description
    assert restored.parameters_schema == defn.parameters_schema
    assert restored.implementation_type == ImplementationType.CALLABLE
    assert restored.implementation_ref == "math.fsum"


def test_tool_definition_from_dict_minimal() -> None:
    data = {"id": "abc", "name": "foo", "description": "bar"}
    defn = ToolDefinition.from_dict(data)
    assert defn.id == "abc"
    assert defn.implementation_type == ImplementationType.MOCK


def test_tool_definition_conflict_error() -> None:
    err = ToolDefinitionConflictError("my_tool")
    assert "my_tool" in str(err)


def test_tool_definition_not_found_error() -> None:
    err = ToolDefinitionNotFoundError("missing_id")
    assert "missing_id" in str(err)
