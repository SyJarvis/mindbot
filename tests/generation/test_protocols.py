"""Tests for generation/protocols.py."""

from __future__ import annotations

import pytest

from mindbot.generation.protocols import (
    GenerationRequest,
    GenerationResult,
    GenerationStatus,
    GenerationValidationError,
    GenerationPersistenceError,
)


def test_generation_request_valid() -> None:
    req = GenerationRequest(description="Calculate Fibonacci number")
    assert req.description == "Calculate Fibonacci number"
    assert req.artifact_type == "tool"


def test_generation_request_empty_description_raises() -> None:
    with pytest.raises(ValueError, match="description"):
        GenerationRequest(description="   ")


def test_generation_result_succeeded() -> None:
    req = GenerationRequest(description="test")
    result = GenerationResult(request=req, status=GenerationStatus.READY, artifact="x")
    assert result.succeeded is True


def test_generation_result_failed() -> None:
    req = GenerationRequest(description="test")
    result = GenerationResult(request=req, status=GenerationStatus.FAILED)
    assert result.succeeded is False


def test_generation_validation_error_stores_raw() -> None:
    err = GenerationValidationError("bad json", raw='{"broken": }')
    assert err.raw == '{"broken": }'
    assert "bad json" in str(err)


def test_generation_persistence_error_stores_id() -> None:
    err = GenerationPersistenceError("tool_123", cause=OSError("disk full"))
    assert err.artifact_id == "tool_123"
    assert "disk full" in str(err)
