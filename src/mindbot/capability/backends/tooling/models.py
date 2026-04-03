"""Static tool data models and the ``@tool`` decorator.

These models represent *statically defined* tools – tools whose handler is a
Python callable known at import time.  They differ from
:class:`~mindbot.generation.models.ToolDefinition`, which represents tools
generated dynamically by the LLM.

Both ultimately expose the same JSON Schema interface to LLM providers via
:meth:`Tool.parameters_json_schema`.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, get_type_hints


# ---------------------------------------------------------------------------
# Parameter & Tool dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ToolParameter:
    """Describes a single parameter accepted by a tool."""

    name: str
    type: str  # JSON Schema type: string, number, integer, boolean, array, object
    description: str = ""
    required: bool = True
    default: Any = None
    enum: list[str] | None = None


@dataclass
class Tool:
    """Internal unified representation of a statically callable tool.

    Converts to provider-specific formats via :meth:`to_openai_format` /
    :meth:`to_anthropic_format`.
    """

    name: str
    description: str
    parameters: list[ToolParameter] = field(default_factory=list)
    parameters_schema_override: dict[str, Any] | None = None
    handler: Callable[..., Any] | None = None

    # ------------------------------------------------------------------
    # JSON Schema helpers
    # ------------------------------------------------------------------

    def parameters_json_schema(self) -> dict[str, Any]:
        """Build a JSON Schema ``object`` for the tool's parameters."""
        if self.parameters_schema_override is not None:
            return self.parameters_schema_override

        properties: dict[str, Any] = {}
        required: list[str] = []
        for p in self.parameters:
            prop: dict[str, Any] = {"type": p.type}
            if p.description:
                prop["description"] = p.description
            if p.enum:
                prop["enum"] = p.enum
            if p.default is not None:
                prop["default"] = p.default
            properties[p.name] = prop
            if p.required:
                required.append(p.name)
        schema: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required
        return schema

    # ------------------------------------------------------------------
    # Provider format converters
    # ------------------------------------------------------------------

    def to_openai_format(self) -> dict[str, Any]:
        """Return the OpenAI ``tools`` list entry for this tool."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_json_schema(),
            },
        }

    def to_anthropic_format(self) -> dict[str, Any]:
        """Return the Anthropic tool schema for this tool."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters_json_schema(),
        }


# ---------------------------------------------------------------------------
# @tool decorator
# ---------------------------------------------------------------------------

# Mapping from Python type annotations to JSON Schema types.
_PY_TO_JSON_TYPE: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def tool(
    name: str | None = None,
    description: str | None = None,
) -> Callable[[Callable[..., Any]], Tool]:
    """Decorator that converts a plain function into a :class:`Tool`.

    Usage::

        @tool()
        def search_web(query: str, max_results: int = 5) -> str:
            \"\"\"Search the web for information.\"\"\"
            ...

    The function's signature, type hints, and docstring are inspected to
    build the tool's parameter schema automatically.
    """

    def decorator(func: Callable[..., Any]) -> Tool:
        tool_name = name or func.__name__
        tool_desc = description or (inspect.getdoc(func) or "")

        sig = inspect.signature(func)
        hints = get_type_hints(func)
        params: list[ToolParameter] = []

        for pname, param in sig.parameters.items():
            if pname in ("self", "cls"):
                continue
            py_type = hints.get(pname, str)
            json_type = _PY_TO_JSON_TYPE.get(py_type, "string")
            has_default = param.default is not inspect.Parameter.empty
            params.append(
                ToolParameter(
                    name=pname,
                    type=json_type,
                    description="",
                    required=not has_default,
                    default=param.default if has_default else None,
                )
            )

        return Tool(
            name=tool_name,
            description=tool_desc,
            parameters=params,
            handler=func,
        )

    return decorator
