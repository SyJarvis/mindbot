"""Meta tool for creating dynamic tools at runtime."""

from __future__ import annotations

from typing import Any

from src.mindbot.capability.backends.tooling.models import Tool
from src.mindbot.generation.dynamic_manager import DynamicToolManager
from src.mindbot.generation.models import ImplementationType


def create_tool_creation_tool(manager: DynamicToolManager) -> Tool:
    """Create the `create_tool` meta-tool bound to *manager*."""

    async def create_tool(
        description: str,
        name_hint: str | None = None,
        parameters_schema: dict[str, Any] | None = None,
        implementation_type: str = "mock",
        implementation_ref: str = "",
        persist: bool = True,
        replace: bool = False,
    ) -> str:
        hints: dict[str, Any] = {}
        if name_hint:
            hints["name"] = name_hint
        if parameters_schema:
            hints["parameters_schema"] = parameters_schema

        defn = await manager.register_and_persist(
            description,
            hints=hints,
            persist=persist,
            replace=replace,
            implementation_type=ImplementationType(implementation_type),
            implementation_ref=implementation_ref or None,
        )
        return (
            f"Created tool '{defn.name}' "
            f"(id: {defn.id}, implementation: {defn.implementation_type.value}, persist={persist})."
        )

    return Tool(
        name="create_tool",
        description=(
            "Generate and register a new tool definition from a natural-language description. "
            "The created tool becomes available after capability refresh."
        ),
        parameters_schema_override={
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "What the new tool should do.",
                },
                "name_hint": {
                    "type": "string",
                    "description": "Optional preferred snake_case tool name.",
                },
                "parameters_schema": {
                    "type": "object",
                    "description": "Optional JSON Schema object for the tool parameters.",
                },
                "implementation_type": {
                    "type": "string",
                    "enum": ["mock", "callable"],
                    "description": "How the generated tool should be executed.",
                    "default": "mock",
                },
                "implementation_ref": {
                    "type": "string",
                    "description": "Callable import path when implementation_type is callable.",
                    "default": "",
                },
                "persist": {
                    "type": "boolean",
                    "description": "Persist the tool to disk for future sessions.",
                    "default": True,
                },
                "replace": {
                    "type": "boolean",
                    "description": "Replace an existing dynamic tool with the same name.",
                    "default": False,
                },
            },
            "required": ["description"],
        },
        handler=create_tool,
    )
