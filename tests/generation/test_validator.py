"""Tests for generation/validator.py."""

from __future__ import annotations

import json

import pytest

from mindbot.generation.models import ToolDefinition
from mindbot.generation.protocols import GenerationRequest, GenerationValidationError
from mindbot.generation.validator import (
    ToolDefinitionValidator,
    validate_tool_definition,
)
from mindbot.generation.models import ToolDefinitionError


# ---------------------------------------------------------------------------
# validate_tool_definition (typed)
# ---------------------------------------------------------------------------


def test_validate_valid_definition() -> None:
    defn = ToolDefinition(
        name="search_web",
        description="Search the web for a query",
        parameters_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    )
    validate_tool_definition(defn)  # should not raise


def test_validate_empty_name_raises() -> None:
    defn = ToolDefinition(name="", description="something")
    with pytest.raises(ToolDefinitionError, match="name"):
        validate_tool_definition(defn)


def test_validate_invalid_name_raises() -> None:
    defn = ToolDefinition(name="123bad", description="something")
    with pytest.raises(ToolDefinitionError, match="invalid"):
        validate_tool_definition(defn)


def test_validate_name_too_long_raises() -> None:
    defn = ToolDefinition(name="a" * 65, description="something")
    with pytest.raises(ToolDefinitionError):
        validate_tool_definition(defn)


def test_validate_empty_description_raises() -> None:
    defn = ToolDefinition(name="my_tool", description="   ")
    with pytest.raises(ToolDefinitionError, match="description"):
        validate_tool_definition(defn)


def test_validate_non_object_schema_raises() -> None:
    defn = ToolDefinition(
        name="my_tool",
        description="ok",
        parameters_schema={"type": "array"},
    )
    with pytest.raises(ToolDefinitionError, match="type.*object"):
        validate_tool_definition(defn)


def test_validate_empty_schema_is_ok() -> None:
    defn = ToolDefinition(name="no_params", description="Has no parameters")
    validate_tool_definition(defn)  # empty schema is valid


def test_validate_property_missing_type_raises() -> None:
    defn = ToolDefinition(
        name="my_tool",
        description="ok",
        parameters_schema={
            "type": "object",
            "properties": {"x": {"description": "no type field"}},
        },
    )
    with pytest.raises(ToolDefinitionError, match="missing 'type'"):
        validate_tool_definition(defn)


# ---------------------------------------------------------------------------
# ToolDefinitionValidator (raw LLM output)
# ---------------------------------------------------------------------------


@pytest.fixture()
def validator() -> ToolDefinitionValidator:
    return ToolDefinitionValidator()


@pytest.fixture()
def sample_request() -> GenerationRequest:
    return GenerationRequest(description="Compute the nth Fibonacci number")


def test_validator_valid_json(
    validator: ToolDefinitionValidator,
    sample_request: GenerationRequest,
) -> None:
    raw = json.dumps({
        "name": "fibonacci",
        "description": "Returns the nth Fibonacci number",
        "parameters_schema": {
            "type": "object",
            "properties": {"n": {"type": "integer"}},
        },
        "implementation_type": "mock",
        "implementation_ref": "",
    })
    defn = validator.validate(raw, sample_request)
    assert defn.name == "fibonacci"


def test_validator_strips_markdown_fences(
    validator: ToolDefinitionValidator,
    sample_request: GenerationRequest,
) -> None:
    inner = {"name": "my_tool", "description": "Does something"}
    raw = f"```json\n{json.dumps(inner)}\n```"
    defn = validator.validate(raw, sample_request)
    assert defn.name == "my_tool"


def test_validator_invalid_json_raises(
    validator: ToolDefinitionValidator,
    sample_request: GenerationRequest,
) -> None:
    with pytest.raises(GenerationValidationError, match="not valid JSON"):
        validator.validate("{broken json}", sample_request)


def test_validator_missing_required_field_raises(
    validator: ToolDefinitionValidator,
    sample_request: GenerationRequest,
) -> None:
    raw = json.dumps({"name": "only_name"})
    with pytest.raises(GenerationValidationError, match="missing required"):
        validator.validate(raw, sample_request)


def test_validator_invalid_name_raises(
    validator: ToolDefinitionValidator,
    sample_request: GenerationRequest,
) -> None:
    raw = json.dumps({"name": "1_invalid", "description": "desc"})
    with pytest.raises(GenerationValidationError):
        validator.validate(raw, sample_request)
