"""Streaming executor – provider-level streaming adapter.

提供两种接口：
1. execute_stream() → ChatResponse：收集所有 chunk 后返回完整响应（供 chat() 使用）
2. stream() → AsyncIterator[str]：逐 token yield，流结束后通过 last_chat_response 属性提供完整响应（供 chat_stream() 使用）
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Callable

from mindbot.agent.models import AgentEvent
from mindbot.context.models import ChatResponse, Message
from mindbot.providers.adapter import ProviderAdapter
from mindbot.logging import logger




class StreamingExecutor:
    """Provider-level streaming adapter."""

    def __init__(self, llm: ProviderAdapter) -> None:
        self._llm = llm
        self._last_chat_response: ChatResponse | None = None

    async def execute_stream(
        self,
        messages: list[Message],
        on_event: Callable[[AgentEvent], None] | None = None,
        tools: list[Any] | None = None,
        **llm_kwargs: Any,
    ) -> ChatResponse:
        """流式收集所有 chunk 后返回完整 ChatResponse（供 TurnEngine.run 使用）。

        始终通过 chat_stream 逐 token 输出，同时在流结束后从
        last_chat_response 中提取 tool_calls。
        """
        try:
            if on_event:
                on_event(AgentEvent.thinking())

            tool_calls_out: list[Any] = []
            content_parts: list[str] = []
            async for chunk in self._llm.chat_stream(
                messages, tools=tools, tool_calls_out=tool_calls_out, **llm_kwargs,
            ):
                if chunk:
                    content_parts.append(chunk)
                    if on_event:
                        on_event(AgentEvent.delta(chunk))

            return ChatResponse(
                content="".join(content_parts),
                tool_calls=tool_calls_out or None,
                finish_reason="tool_calls" if tool_calls_out else "stop",
            )

        except Exception as e:
            logger.error(f"Error in execute_stream: {e}")
            if on_event:
                on_event(AgentEvent.error(str(e)))
            raise

    async def stream(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        **llm_kwargs: Any,
    ) -> AsyncIterator[str]:
        """逐 token yield，流结束后存储完整 ChatResponse 到 last_chat_response。

        用法::
            async for chunk in executor.stream(messages, tools=tools):
                print(chunk, end="")
            response = executor.last_chat_response  # 完整响应
        """
        tool_calls_out: list[Any] = []
        content_parts: list[str] = []

        try:
            async for chunk in self._llm.chat_stream(
                messages, tools=tools, tool_calls_out=tool_calls_out, **llm_kwargs,
            ):
                if chunk:
                    content_parts.append(chunk)
                    yield chunk

        except Exception:
            self._last_chat_response = ChatResponse(content="", tool_calls=None, finish_reason="stop")
            raise

        self._last_chat_response = ChatResponse(
            content="".join(content_parts),
            tool_calls=tool_calls_out or None,
            finish_reason="tool_calls" if tool_calls_out else "stop",
        )

    @property
    def last_chat_response(self) -> ChatResponse:
        """stream() 结束后的完整 ChatResponse。"""
        if self._last_chat_response is None:
            raise RuntimeError("last_chat_response not available until stream() completes")
        return self._last_chat_response
