"""Tests for generation/tool_generator.py – ToolGenerator with MockStrategy."""

from __future__ import annotations

import pytest

from mindbot.generation.models import ToolDefinition
from mindbot.generation.protocols import GenerationRequest, GenerationStatus
from mindbot.generation.tool_generator import MockStrategy, ToolGenerator


@pytest.fixture()
def generator() -> ToolGenerator:
    return ToolGenerator(MockStrategy())


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_succeeds(generator: ToolGenerator) -> None:
    req = GenerationRequest(description="Calculate the sum of two numbers")
    result = await generator.generate(req)
    assert result.succeeded
    assert isinstance(result.artifact, ToolDefinition)
    assert result.status == GenerationStatus.READY
    assert result.attempts == 1


@pytest.mark.asyncio
async def test_generated_name_is_derived_from_description(generator: ToolGenerator) -> None:
    req = GenerationRequest(description="send email to user")
    result = await generator.generate(req)
    assert result.succeeded
    assert result.artifact.name  # non-empty snake_case name


@pytest.mark.asyncio
async def test_generate_with_hints_override(generator: ToolGenerator) -> None:
    override = MockStrategy(override={"name": "custom_tool", "description": "override"})
    gen = ToolGenerator(override)
    req = GenerationRequest(description="whatever", hints={"name": "custom_tool"})
    result = await gen.generate(req)
    assert result.succeeded
    assert result.artifact.name == "custom_tool"


# ---------------------------------------------------------------------------
# Retry / failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_retries_on_validation_failure() -> None:
    """Strategy that always returns invalid JSON triggers max retries."""
    class BadStrategy:
        async def call(self, request: GenerationRequest) -> str:
            return "not json at all"

    gen = ToolGenerator(BadStrategy(), max_attempts=2)
    req = GenerationRequest(description="a thing")
    result = await gen.generate(req)

    assert not result.succeeded
    assert result.status == GenerationStatus.FAILED
    assert result.attempts == 2
    assert result.error is not None


@pytest.mark.asyncio
async def test_generate_succeeds_on_second_attempt() -> None:
    call_count = 0

    class FlakyStrategy:
        async def call(self, request: GenerationRequest) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "broken"
            return '{"name": "stable_tool", "description": "works on retry"}'

    gen = ToolGenerator(FlakyStrategy(), max_attempts=3)
    result = await gen.generate(GenerationRequest(description="test"))
    assert result.succeeded
    assert result.artifact.name == "stable_tool"
    assert result.attempts == 2
