"""Static tool executor – runs tool handlers and collects results."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

from mindbot.capability.backends.tooling.registry import ToolRegistry
from mindbot.context.models import ToolCall, ToolResult
from mindbot.utils import get_logger, truncate

logger = get_logger("tooling.executor")

_MAX_RESULT_LENGTH = 50_000


class ToolExecutor:
    """Execute tool calls against a :class:`ToolRegistry`."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    # ------------------------------------------------------------------
    # Single execution
    # ------------------------------------------------------------------

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        """Execute a single *tool_call* and return a :class:`ToolResult`."""
        tool = self._registry.get(tool_call.name)
        if tool is None:
            logger.warning("Tool not found: %s", tool_call.name)
            return ToolResult(
                tool_call_id=tool_call.id,
                success=False,
                error=f"Tool '{tool_call.name}' is not registered",
            )

        if tool.handler is None:
            return ToolResult(
                tool_call_id=tool_call.id,
                success=False,
                error=f"Tool '{tool_call.name}' has no handler",
            )

        try:
            result = await self._invoke(tool.handler, tool_call.arguments)
            content = truncate(str(result), _MAX_RESULT_LENGTH)
            return ToolResult(
                tool_call_id=tool_call.id,
                success=True,
                content=content,
            )
        except Exception as exc:
            logger.exception("Tool '%s' raised an exception", tool_call.name)
            return ToolResult(
                tool_call_id=tool_call.id,
                success=False,
                error=f"{type(exc).__name__}: {exc}",
            )

    # ------------------------------------------------------------------
    # Batch execution
    # ------------------------------------------------------------------

    async def execute_batch(self, tool_calls: list[ToolCall]) -> list[ToolResult]:
        """Execute *tool_calls* concurrently and return results in the same order."""
        tasks = [self.execute(tc) for tc in tool_calls]
        return list(await asyncio.gather(*tasks))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    async def _invoke(handler: Any, arguments: dict[str, Any]) -> Any:
        """Invoke *handler* – supports both sync and async callables."""
        if inspect.iscoroutinefunction(handler):
            return await handler(**arguments)
        return await asyncio.to_thread(handler, **arguments)
