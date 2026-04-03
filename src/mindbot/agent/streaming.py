"""Streaming executor – provider-level streaming adapter.

This module wraps :class:`~mindbot.providers.adapter.ProviderAdapter` to
provide a uniform ``execute`` / ``execute_stream`` interface with event
generation for real-time UI updates.

Control-flow decisions (tools vs. no-tools, retry, etc.) belong to
:class:`~mindbot.agent.turn_engine.TurnEngine`.  This executor only
concerns itself with the LLM call mechanics.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Callable

from mindbot.agent.models import AgentEvent
from mindbot.context.models import ChatResponse, Message, ToolCall
from mindbot.providers.adapter import ProviderAdapter
from mindbot.utils import get_logger


logger = get_logger("agent.streaming")


class StreamingExecutor:
    """Provider-level streaming adapter.

    Wraps :class:`ProviderAdapter` to:
    1. Stream LLM responses in real-time (when no tools are bound).
    2. Fall back to a non-streaming call when tools are active (most
       providers require a complete response to parse tool_calls).
    3. Emit :class:`AgentEvent` for each chunk / lifecycle transition.
    """

    def __init__(self, llm: ProviderAdapter) -> None:
        self._llm = llm

    async def execute_stream(
        self,
        messages: list[Message],
        on_event: Callable[[AgentEvent], None] | None = None,
        tools: list[Any] | None = None,
        **llm_kwargs: Any,
    ) -> ChatResponse:
        """Execute an LLM call, streaming when possible.

        When *tools* are provided the call is non-streaming because most
        providers need the full response to parse ``tool_calls``.
        """
        if on_event:
            on_event(AgentEvent.thinking())

        if tools:
            return await self._execute_with_tools(messages, on_event, tools, **llm_kwargs)

        return await self._execute_stream_only(messages, on_event, **llm_kwargs)

    async def _execute_with_tools(
        self,
        messages: list[Message],
        on_event: Callable[[AgentEvent], None] | None,
        tools: list[Any],
        **llm_kwargs: Any,
    ) -> ChatResponse:
        """Non-streaming call when tools are bound."""
        try:
            response = await self._llm.chat(
                messages,
                tools=tools,
                **llm_kwargs,
            )

            if on_event and response.content:
                on_event(AgentEvent.delta(response.content))

            return response

        except Exception as e:
            logger.error(f"Error in execute_with_tools: {e}")
            if on_event:
                on_event(AgentEvent.error(str(e)))
            raise

    async def _execute_stream_only(
        self,
        messages: list[Message],
        on_event: Callable[[AgentEvent], None] | None,
        **llm_kwargs: Any,
    ) -> ChatResponse:
        """Streaming call without tools."""
        content_parts: list[str] = []

        try:
            async for chunk in self._llm.chat_stream(messages, **llm_kwargs):
                if chunk:
                    content_parts.append(chunk)
                    if on_event:
                        on_event(AgentEvent.delta(chunk))

            full_content = "".join(content_parts)

            return ChatResponse(
                content=full_content,
                tool_calls=None,
                finish_reason="stop",
            )

        except Exception as e:
            logger.error(f"Error in execute_stream_only: {e}")
            if on_event:
                on_event(AgentEvent.error(str(e)))
            raise


async def stream_with_events(
    llm: ProviderAdapter,
    messages: list[Message],
    on_event: Callable[[AgentEvent], None] | None = None,
    tools: list[Any] | None = None,
    **llm_kwargs: Any,
) -> ChatResponse:
    """Convenience function for streaming LLM calls with events."""
    executor = StreamingExecutor(llm)
    return await executor.execute_stream(messages, on_event, tools, **llm_kwargs)
