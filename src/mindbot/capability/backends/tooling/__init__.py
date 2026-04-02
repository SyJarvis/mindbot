"""Static tool primitives – moved here from ``mindbot.tools`` as part of the
Phase 2 激进重构.

Imports for the public API:

    from mindbot.capability.backends.tooling import Tool, ToolParameter, tool
    from mindbot.capability.backends.tooling import ToolRegistry, ToolExecutor
"""

from src.mindbot.capability.backends.tooling.executor import ToolExecutor
from src.mindbot.capability.backends.tooling.models import Tool, ToolParameter, tool
from src.mindbot.capability.backends.tooling.registry import ToolRegistry

__all__ = [
    "Tool",
    "ToolParameter",
    "ToolRegistry",
    "ToolExecutor",
    "tool",
]
