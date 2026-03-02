"""Tests for capability/backends/tool_backend.py – ToolBackend.

Covers:
- Static tool capability registration and execution.
- Dynamic tool registration and execution (mock mode).
- Conflict detection between static and dynamic entries.
- Startup load (restart simulation).
- Runtime incremental registration + facade refresh.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mindbot.capability.backends.tool_backend import ToolBackend, _tool_to_capability, _definition_to_capability
from mindbot.capability.backends.tooling.models import Tool, ToolParameter, tool
from mindbot.capability.backends.tooling.registry import ToolRegistry
from mindbot.capability.facade import CapabilityFacade
from mindbot.capability.models import (
    CapabilityConflictError,
    CapabilityNotFoundError,
    CapabilityType,
)
from mindbot.generation.models import ImplementationType, ToolDefinition
from mindbot.generation.registry import ToolDefinitionRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_static_tool(name: str = "static_echo") -> Tool:
    @tool()
    def static_echo(message: str) -> str:
        """Echo the message."""
        return message

    static_echo.name = name
    return static_echo


def _make_dynamic_defn(name: str = "dyn_tool") -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description="A dynamically generated mock tool",
        implementation_type=ImplementationType.MOCK,
    )


# ---------------------------------------------------------------------------
# list_capabilities
# ---------------------------------------------------------------------------


def test_list_capabilities_empty() -> None:
    backend = ToolBackend()
    assert backend.list_capabilities() == []


def test_list_capabilities_static_only(tmp_path: Path) -> None:
    t = _make_static_tool()
    registry = ToolRegistry.from_tools([t])
    backend = ToolBackend(static_registry=registry)
    caps = backend.list_capabilities()
    assert len(caps) == 1
    assert caps[0].id == t.name
    assert caps[0].capability_type == CapabilityType.TOOL


def test_list_capabilities_dynamic_only(tmp_path: Path) -> None:
    def_registry = ToolDefinitionRegistry(store_dir=tmp_path)
    backend = ToolBackend(definition_registry=def_registry)
    defn = _make_dynamic_defn()
    backend.register_dynamic(defn, persist=False)
    caps = backend.list_capabilities()
    assert any(c.id == defn.id for c in caps)


def test_list_capabilities_combined(tmp_path: Path) -> None:
    t = _make_static_tool()
    static_reg = ToolRegistry.from_tools([t])
    def_reg = ToolDefinitionRegistry(store_dir=tmp_path)
    backend = ToolBackend(static_registry=static_reg, definition_registry=def_reg)
    defn = _make_dynamic_defn("dyn_one")
    backend.register_dynamic(defn, persist=False)
    cap_ids = {c.id for c in backend.list_capabilities()}
    assert t.name in cap_ids
    assert defn.id in cap_ids


# ---------------------------------------------------------------------------
# execute – static
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_static_tool() -> None:
    @tool()
    def greet(name: str) -> str:
        """Return greeting."""
        return f"Hello, {name}!"

    registry = ToolRegistry.from_tools([greet])
    backend = ToolBackend(static_registry=registry)
    result = await backend.execute(greet.name, {"name": "Alice"})
    assert result == "Hello, Alice!"


@pytest.mark.asyncio
async def test_execute_static_missing_raises() -> None:
    backend = ToolBackend()
    with pytest.raises(CapabilityNotFoundError):
        await backend.execute("nonexistent", {})


# ---------------------------------------------------------------------------
# execute – dynamic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_dynamic_mock(tmp_path: Path) -> None:
    def_reg = ToolDefinitionRegistry(store_dir=tmp_path)
    backend = ToolBackend(definition_registry=def_reg)
    defn = _make_dynamic_defn("mock_cap")
    backend.register_dynamic(defn, persist=False)
    result = await backend.execute(defn.id, {"x": 1})
    assert "mock" in result.lower()


@pytest.mark.asyncio
async def test_execute_dynamic_missing_raises(tmp_path: Path) -> None:
    backend = ToolBackend(definition_registry=ToolDefinitionRegistry(store_dir=tmp_path))
    with pytest.raises(CapabilityNotFoundError):
        await backend.execute("no-such-id", {})


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------


def test_register_static_conflict_raises() -> None:
    t = _make_static_tool("same_name")
    registry = ToolRegistry.from_tools([t])
    backend = ToolBackend(static_registry=registry)
    t2 = _make_static_tool("same_name")
    with pytest.raises(CapabilityConflictError):
        backend.register_static(t2)


def test_register_static_replace() -> None:
    t = _make_static_tool("replaceable")
    registry = ToolRegistry.from_tools([t])
    backend = ToolBackend(static_registry=registry)
    t2 = _make_static_tool("replaceable")
    backend.register_static(t2, replace=True)
    # No exception, and routing still present
    assert "replaceable" in backend._routing  # noqa: SLF001


def test_register_dynamic_conflict_raises(tmp_path: Path) -> None:
    def_reg = ToolDefinitionRegistry(store_dir=tmp_path)
    backend = ToolBackend(definition_registry=def_reg)
    defn = _make_dynamic_defn("unique_dyn")
    backend.register_dynamic(defn, persist=False)
    defn2 = ToolDefinition(id=defn.id, name="other_name", description="conflict on id")
    with pytest.raises(CapabilityConflictError):
        backend.register_dynamic(defn2, persist=False)


# ---------------------------------------------------------------------------
# Persistence – startup load (restart simulation)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_definitions_restores_after_restart(tmp_path: Path) -> None:
    # Phase 1: create and save a dynamic tool
    def_reg1 = ToolDefinitionRegistry(store_dir=tmp_path)
    backend1 = ToolBackend(definition_registry=def_reg1)
    defn = _make_dynamic_defn("persistent_tool")
    backend1.register_dynamic(defn, persist=True)

    # Phase 2: new process – fresh backend, load from disk
    def_reg2 = ToolDefinitionRegistry(store_dir=tmp_path)
    backend2 = ToolBackend(definition_registry=def_reg2)
    loaded = backend2.load_definitions()

    assert loaded == 1
    result = await backend2.execute(defn.id, {})
    assert "mock" in result.lower()


# ---------------------------------------------------------------------------
# ExtensionBackend protocol compliance
# ---------------------------------------------------------------------------


def test_backend_satisfies_protocol() -> None:
    from mindbot.capability.backends.base import ExtensionBackend
    assert isinstance(ToolBackend(), ExtensionBackend)


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------


def test_tool_to_capability() -> None:
    t = Tool(name="my_func", description="does things")
    cap = _tool_to_capability(t)
    assert cap.id == "my_func"
    assert cap.capability_type == CapabilityType.TOOL


def test_definition_to_capability() -> None:
    defn = _make_dynamic_defn("gen_func")
    cap = _definition_to_capability(defn)
    assert cap.id == defn.id
    assert cap.name == "gen_func"
    assert cap.capability_type == CapabilityType.TOOL


# ---------------------------------------------------------------------------
# Integration: ToolBackend + CapabilityFacade
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_facade_with_tool_backend_executes_static() -> None:
    @tool()
    def multiply(a: int, b: int) -> str:
        """Multiply two integers."""
        return str(a * b)

    registry = ToolRegistry.from_tools([multiply])
    backend = ToolBackend(static_registry=registry)

    facade = CapabilityFacade()
    facade.add_backend(backend)

    result = await facade.execute(multiply.name, {"a": 6, "b": 7})
    assert result == "42"


@pytest.mark.asyncio
async def test_facade_refresh_makes_new_dynamic_tool_visible(tmp_path: Path) -> None:
    def_reg = ToolDefinitionRegistry(store_dir=tmp_path)
    backend = ToolBackend(definition_registry=def_reg)

    facade = CapabilityFacade()
    facade.add_backend(backend)

    # Initially empty
    assert facade.list_capabilities() == []

    # Register a new dynamic tool at runtime
    defn = _make_dynamic_defn("new_runtime_tool")
    backend.register_dynamic(defn, persist=False)
    facade.refresh_registry()

    from mindbot.capability.models import CapabilityQuery
    cap = facade.resolve(CapabilityQuery(capability_id=defn.id))
    assert cap.id == defn.id

    result = await facade.execute(defn.id, {})
    assert "mock" in result.lower()
