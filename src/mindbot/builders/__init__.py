"""MindBot builders – unified construction helpers.

Public API::

    from mindbot.builders import create_llm, create_agent, create_tool_registry
    from mindbot.builders import parse_model_ref

These helpers replace hand-rolled provider/config assembly and ensure a
single, consistent object-construction path regardless of caller context.
"""

from src.mindbot.builders.agent_builder import create_agent
from src.mindbot.builders.llm_builder import create_llm
from src.mindbot.builders.model_ref import parse_model_ref
from src.mindbot.builders.tool_builder import create_tool_registry

__all__ = [
    "create_agent",
    "create_llm",
    "create_tool_registry",
    "parse_model_ref",
]
