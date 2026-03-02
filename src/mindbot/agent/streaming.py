"""Streaming executor for real-time agent responses.

This module provides streaming support for LLM calls with event generation
for real-time UI updates.
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
    """Executor that provides streaming responses with events.

    This executor wraps the ProviderAdapter to:
    1. Stream LLM responses in real-time
    2. Generate AgentEvent for each chunk
    3. Support tool calls after streaming completes
    4. Handle errors gracefully

    Usage:
        executor = StreamingExecutor(llm_adapter)

        response = await executor.execute_stream(
            messages=messages,
            on_event=lambda e: print(f"Event: {e.type}"),
        )
    """

    def __init__(self, llm: ProviderAdapter) -> None:
        """Initialize the streaming executor.

        Args:
            llm: The provider adapter for LLM calls
        """
        self._llm = llm

    async def execute_stream(
        self,
        messages: list[Message],
        on_event: Callable[[AgentEvent], None] | None = None,
        tools: list[Any] | None = None,
        **llm_kwargs: Any,
    ) -> ChatResponse:
        """Execute LLM call with streaming.

        This method:
        1. Sends thinking event
        2. Streams response chunks
        3. Sends delta events for each chunk
        4. Returns final ChatResponse

        Args:
            messages: Conversation messages
            on_event: Optional callback for events
            tools: Optional tool definitions for function calling
            **llm_kwargs: Additional LLM parameters

        Returns:
            ChatResponse with content and optional tool_calls
        """
        # Send thinking event
        if on_event:
            on_event(AgentEvent.thinking())

        # Note: When tools are provided, we need to use non-streaming mode
        # because tool_calls come in the final response
        if tools:
            return await self._execute_with_tools(messages, on_event, tools, **llm_kwargs)

        # Stream without tools
        return await self._execute_stream_only(messages, on_event, **llm_kwargs)

    async def _execute_with_tools(
        self,
        messages: list[Message],
        on_event: Callable[[AgentEvent], None] | None,
        tools: list[Any],
        **llm_kwargs: Any,
    ) -> ChatResponse:
        """Execute with tools (non-streaming).

        When tools are provided, most providers don't support streaming
        because tool_calls need to be parsed from the final response.
        """
        try:
            response = await self._llm.chat(
                messages,
                tools=tools,
                **llm_kwargs,
            )

            # Send content as a single delta event
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
        """Execute streaming without tools.

        This collects all chunks and builds a ChatResponse.
        """
        content_parts: list[str] = []

        try:
            async for chunk in self._llm.chat_stream(messages, **llm_kwargs):
                if chunk:
                    content_parts.append(chunk)
                    if on_event:
                        on_event(AgentEvent.delta(chunk))

            # Build ChatResponse from collected content
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
    """Convenience function for streaming LLM calls with events.

    Args:
        llm: The provider adapter
        messages: Conversation messages
        on_event: Optional event callback
        tools: Optional tool definitions
        **llm_kwargs: Additional LLM parameters

    Returns:
        ChatResponse with content and optional tool_calls
    """
    executor = StreamingExecutor(llm)
    return await executor.execute_stream(messages, on_event, tools, **llm_kwargs)
