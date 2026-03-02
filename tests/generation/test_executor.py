"""Tests for generation/executor.py – DynamicToolExecutor."""

from __future__ import annotations

import pytest

from mindbot.capability.models import CapabilityExecutionError, CapabilityNotFoundError
from mindbot.generation.executor import DynamicToolExecutor
from mindbot.generation.models import ImplementationType, ToolDefinition


@pytest.fixture()
def executor() -> DynamicToolExecutor:
    return DynamicToolExecutor()


@pytest.fixture()
def mock_defn() -> ToolDefinition:
    return ToolDefinition(name="echo_tool", description="Echo back args", implementation_type=ImplementationType.MOCK)


@pytest.fixture()
def callable_defn() -> ToolDefinition:
    return ToolDefinition(
        name="add_tool",
        description="Add two numbers",
        implementation_type=ImplementationType.CALLABLE,
        implementation_ref="tests.generation.helpers.add",
    )


# ---------------------------------------------------------------------------
# MOCK mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_mode_returns_echo(executor: DynamicToolExecutor, mock_defn: ToolDefinition) -> None:
    result = await executor.execute(mock_defn, {"x": "hello"})
    assert "echo_tool" in result
    assert "mock" in result.lower()


@pytest.mark.asyncio
async def test_mock_mode_with_context(executor: DynamicToolExecutor, mock_defn: ToolDefinition) -> None:
    result = await executor.execute(mock_defn, {}, context={"session": "s1"})
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# CALLABLE mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_callable_mode_resolves_and_executes(
    executor: DynamicToolExecutor,
    callable_defn: ToolDefinition,
) -> None:
    result = await executor.execute(callable_defn, {"a": 3, "b": 4})
    assert result == "7"


@pytest.mark.asyncio
async def test_callable_mode_caches_handler(
    executor: DynamicToolExecutor,
    callable_defn: ToolDefinition,
) -> None:
    await executor.execute(callable_defn, {"a": 1, "b": 2})
    await executor.execute(callable_defn, {"a": 1, "b": 2})
    # callable should be cached after first resolution
    assert callable_defn.id in executor._callable_cache  # noqa: SLF001


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_callable_mode_empty_ref_raises_not_found(executor: DynamicToolExecutor) -> None:
    defn = ToolDefinition(
        name="bad",
        description="no ref",
        implementation_type=ImplementationType.CALLABLE,
        implementation_ref="",
    )
    with pytest.raises(CapabilityNotFoundError):
        await executor.execute(defn, {})


@pytest.mark.asyncio
async def test_callable_mode_bad_module_raises_not_found(executor: DynamicToolExecutor) -> None:
    defn = ToolDefinition(
        name="bad",
        description="bad module",
        implementation_type=ImplementationType.CALLABLE,
        implementation_ref="nonexistent_module_xyz.func",
    )
    with pytest.raises(CapabilityNotFoundError):
        await executor.execute(defn, {})


@pytest.mark.asyncio
async def test_callable_raises_at_runtime_wraps_to_execution_error(
    executor: DynamicToolExecutor,
) -> None:
    defn = ToolDefinition(
        name="div",
        description="Divide",
        implementation_type=ImplementationType.CALLABLE,
        implementation_ref="tests.generation.helpers.div",
    )
    with pytest.raises(CapabilityExecutionError) as exc_info:
        await executor.execute(defn, {"a": 1.0, "b": 0.0})
    assert exc_info.value.capability_id == defn.id


@pytest.mark.asyncio
async def test_async_callable_is_supported(executor: DynamicToolExecutor) -> None:
    """Verify async handlers are awaited correctly."""
    defn = ToolDefinition(
        name="async_echo",
        description="Echo async",
        implementation_type=ImplementationType.CALLABLE,
        implementation_ref="tests.generation.helpers.async_echo",
    )
    result = await executor.execute(defn, {"message": "hello"})
    assert result == "hello"
