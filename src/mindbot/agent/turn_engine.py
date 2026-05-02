"""Turn engine – unified execution path for one agent turn.

提供两种接口：
1. run() → AgentResponse：完整执行后返回（供 chat() 使用）
2. run_stream() → AsyncIterator[str]：逐 token yield（供 chat_stream() 使用）
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING, Any

from mindbot.agent.models import AgentEvent, AgentResponse, StopReason
from mindbot.agent.streaming import StreamingExecutor
from mindbot.context.models import Message, ToolCall
from mindbot.providers.adapter import ProviderAdapter
from mindbot.utils import get_logger

if TYPE_CHECKING:
    from mindbot.capability.facade import CapabilityFacade
    from mindbot.capability.backends.tooling.models import Tool

logger = get_logger("agent.turn_engine")


class TurnEngine:
    """Execute one complete agent turn using a single shared loop."""

    def __init__(
        self,
        llm: ProviderAdapter,
        tools: list["Tool"] | None = None,
        *,
        max_iterations: int = 20,
        capability_facade: "CapabilityFacade | None" = None,
    ) -> None:
        self._llm = llm
        self._tools = tools or []
        self._max_iterations = max_iterations
        self._capability_facade = capability_facade
        self._streaming_executor = StreamingExecutor(llm)
        self._last_stream_response: AgentResponse | None = None

    # ------------------------------------------------------------------
    # 非流式接口（供 chat() 使用）
    # ------------------------------------------------------------------

    async def run(
        self,
        messages: list[Message],
        on_event: Callable[[AgentEvent], None] | None = None,
        turn_id: str | None = None,
    ) -> AgentResponse:
        """完整执行 turn，返回 AgentResponse。"""
        resolved_turn_id = turn_id or uuid.uuid4().hex
        response = AgentResponse(content="")
        response.metadata["turn_id"] = resolved_turn_id
        initial_len = len(messages)

        try:
            for iteration in range(self._max_iterations):
                should_continue, messages = await self._execute_iteration(
                    messages=messages,
                    iteration=iteration,
                    on_event=on_event,
                    response=response,
                    turn_id=resolved_turn_id,
                )
                if not should_continue:
                    break
            else:
                response.stop_reason = StopReason.MAX_TURNS
                if on_event:
                    on_event(AgentEvent.complete(response.stop_reason))

            if on_event and response.stop_reason == StopReason.COMPLETED:
                on_event(AgentEvent.complete(response.stop_reason))

        except Exception as exc:
            logger.exception("Error while running turn")
            response.stop_reason = StopReason.ERROR
            if on_event:
                on_event(AgentEvent.error(str(exc)))

        self._build_trace(messages, initial_len, response, resolved_turn_id)
        return response

    # ------------------------------------------------------------------
    # 流式接口（供 chat_stream() 使用）
    # ------------------------------------------------------------------

    async def run_stream(
        self,
        messages: list[Message],
        on_event: Callable[[AgentEvent], None] | None = None,
        turn_id: str | None = None,
    ) -> AsyncIterator[str]:
        """逐 token 流式执行 turn。

        工具迭代期间不 yield（工具调用需要完整响应），
        最终文本迭代逐 token yield。

        流结束后通过 last_stream_response 属性获取完整 AgentResponse。
        """
        resolved_turn_id = turn_id or uuid.uuid4().hex
        response = AgentResponse(content="")
        response.metadata["turn_id"] = resolved_turn_id
        initial_len = len(messages)

        try:
            for iteration in range(self._max_iterations):
                # 流式调用 LLM
                if on_event:
                    on_event(AgentEvent.thinking())

                text_chunks: list[str] = []
                async for chunk in self._streaming_executor.stream(
                    messages, tools=self._tools,
                ):
                    if chunk:
                        text_chunks.append(chunk)
                        if on_event:
                            on_event(AgentEvent.delta(chunk))

                llm_response = self._streaming_executor.last_chat_response
                tool_calls = llm_response.tool_calls

                if not tool_calls:
                    # 最终文本回复：逐 token yield
                    response.content = llm_response.content or ""
                    response.metadata["final_message_metadata"] = {
                        "provider": llm_response.provider,
                        "usage": llm_response.usage,
                        "finish_reason": getattr(llm_response.finish_reason, "value", llm_response.finish_reason),
                    }
                    response.stop_reason = StopReason.COMPLETED
                    if on_event:
                        on_event(AgentEvent.complete(response.stop_reason))
                    for chunk in text_chunks:
                        yield chunk
                    break

                # 工具调用：构建 trace，执行工具
                assistant_message = self._make_trace_message(
                    role="assistant",
                    content=llm_response.content or "",
                    turn_id=resolved_turn_id,
                    iteration=iteration,
                    message_kind="assistant_tool_call",
                    tool_calls=tool_calls,
                    reasoning_content=llm_response.reasoning_content,
                    provider=llm_response.provider,
                    usage=llm_response.usage,
                    finish_reason=getattr(llm_response.finish_reason, "value", llm_response.finish_reason),
                )
                messages.append(assistant_message)

                tool_results = await self._execute_tool_calls(
                    tool_calls=tool_calls,
                    on_event=on_event,
                    turn_id=resolved_turn_id,
                    iteration=iteration,
                )

                for tool_call, tr in zip(tool_calls, tool_results, strict=False):
                    messages.append(
                        self._make_trace_message(
                            role="tool",
                            content=tr.content if tr.success else f"Error: {tr.error}",
                            turn_id=resolved_turn_id,
                            iteration=iteration,
                            message_kind="tool_result",
                            tool_call_id=tr.tool_call_id,
                            tool_name=tool_call.name,
                            error=tr.error or None,
                        )
                    )

                if self._has_repeated_tool_call(messages, tool_calls, iteration):
                    response.stop_reason = StopReason.REPEATED_TOOL
                    break
            else:
                response.stop_reason = StopReason.MAX_TURNS

        except Exception as exc:
            logger.exception("Error while running turn (stream)")
            response.stop_reason = StopReason.ERROR
            if on_event:
                on_event(AgentEvent.error(str(exc)))

        self._build_trace(messages, initial_len, response, resolved_turn_id)
        self._last_stream_response = response

    @property
    def last_stream_response(self) -> AgentResponse:
        """run_stream() 结束后的完整 AgentResponse。"""
        if self._last_stream_response is None:
            raise RuntimeError("last_stream_response not available until run_stream() completes")
        return self._last_stream_response

    # ------------------------------------------------------------------
    # 非流式迭代
    # ------------------------------------------------------------------

    async def _execute_iteration(
        self,
        messages: list[Message],
        iteration: int,
        on_event: Callable[[AgentEvent], None] | None,
        response: AgentResponse,
        turn_id: str | None = None,
    ) -> tuple[bool, list[Message]]:
        """Execute one LLM step and optional tool round."""
        llm_response = await self._streaming_executor.execute_stream(
            messages=messages,
            on_event=on_event,
            tools=self._tools,
        )

        tool_calls = llm_response.tool_calls
        if not tool_calls:
            response.content = llm_response.content or ""
            response.metadata["final_message_metadata"] = {
                "provider": llm_response.provider,
                "usage": llm_response.usage,
                "finish_reason": getattr(llm_response.finish_reason, "value", llm_response.finish_reason),
            }
            response.stop_reason = StopReason.COMPLETED
            return False, messages

        assistant_message = self._make_trace_message(
            role="assistant",
            content=llm_response.content or "",
            turn_id=turn_id,
            iteration=iteration,
            message_kind="assistant_tool_call",
            tool_calls=tool_calls,
            reasoning_content=llm_response.reasoning_content,
            provider=llm_response.provider,
            usage=llm_response.usage,
            finish_reason=getattr(llm_response.finish_reason, "value", llm_response.finish_reason),
        )
        messages.append(assistant_message)

        tool_results = await self._execute_tool_calls(
            tool_calls=tool_calls,
            on_event=on_event,
            turn_id=turn_id,
            iteration=iteration,
        )

        for tool_call, tr in zip(tool_calls, tool_results, strict=False):
            messages.append(
                self._make_trace_message(
                    role="tool",
                    content=tr.content if tr.success else f"Error: {tr.error}",
                    turn_id=turn_id,
                    iteration=iteration,
                    message_kind="tool_result",
                    tool_call_id=tr.tool_call_id,
                    tool_name=tool_call.name,
                    error=tr.error or None,
                )
            )

        if self._has_repeated_tool_call(messages, tool_calls, iteration):
            response.stop_reason = StopReason.REPEATED_TOOL
            return False, messages

        return True, messages

    # ------------------------------------------------------------------
    # 工具执行
    # ------------------------------------------------------------------

    async def _execute_tool_calls(
        self,
        tool_calls: list[ToolCall],
        on_event: Callable[[AgentEvent], None] | None,
        turn_id: str | None = None,
        iteration: int | None = None,
    ) -> list[Any]:
        """Execute tool calls via CapabilityFacade."""
        from mindbot.context.models import ToolResult

        results: list[ToolResult] = []

        for tool_call in tool_calls:
            try:
                if on_event:
                    on_event(AgentEvent.tool_executing(
                        tool_name=tool_call.name,
                        call_id=tool_call.id,
                        arguments=tool_call.arguments,
                    ))

                tool_result = await self._resolve_and_execute(tool_call, turn_id)
                results.append(tool_result)

                if on_event:
                    on_event(
                        AgentEvent.tool_result(
                            tool_name=tool_call.name,
                            call_id=tool_call.id,
                            result=tool_result.content if tool_result.success else tool_result.error,
                        )
                    )

            except Exception as exc:
                logger.exception("Error executing tool %s", tool_call.name)
                if on_event:
                    on_event(AgentEvent.error(f"Tool execution error: {exc}"))
                results.append(
                    ToolResult(
                        tool_call_id=tool_call.id,
                        success=False,
                        error=str(exc),
                    )
                )

        return results

    async def _resolve_and_execute(
        self,
        tool_call: ToolCall,
        turn_id: str | None,
    ) -> Any:
        """Single dispatch point for tool execution."""
        from mindbot.context.models import ToolResult

        if self._capability_facade is None:
            raise RuntimeError("Tool execution requires a capability facade")

        from mindbot.capability.models import CapabilityQuery, CapabilityType

        content = await self._capability_facade.resolve_and_execute(
            CapabilityQuery(name=tool_call.name, capability_type=CapabilityType.TOOL),
            arguments=tool_call.arguments,
            context={
                "tool_call_id": tool_call.id,
                "turn_id": turn_id,
            },
        )
        return ToolResult(
            tool_call_id=tool_call.id,
            success=True,
            content=content,
        )

    # ------------------------------------------------------------------
    # Trace 构建
    # ------------------------------------------------------------------

    def _build_trace(
        self,
        messages: list[Message],
        initial_len: int,
        response: AgentResponse,
        turn_id: str,
    ) -> None:
        """构建权威消息 trace 并附加到 response。"""
        trace = messages[initial_len:]
        if response.stop_reason == StopReason.COMPLETED and response.content:
            has_final_assistant = trace and trace[-1].role == "assistant" and not trace[-1].tool_calls
            if not has_final_assistant:
                final_metadata = response.metadata.get("final_message_metadata", {})
                final_msg = self._make_trace_message(
                    role="assistant",
                    content=response.content,
                    turn_id=turn_id,
                    iteration=len([msg for msg in trace if msg.role == "assistant" and msg.tool_calls]) or 0,
                    message_kind="assistant_text",
                    provider=final_metadata.get("provider"),
                    usage=final_metadata.get("usage"),
                    finish_reason=final_metadata.get("finish_reason"),
                    stop_reason=response.stop_reason.value,
                )
                messages.append(final_msg)
                trace = messages[initial_len:]

        if trace:
            trace[-1].stop_reason = response.stop_reason.value
        response.message_trace = trace

    @staticmethod
    def _has_repeated_tool_call(
        messages: list[Message],
        tool_calls: list[ToolCall],
        iteration: int,
    ) -> bool:
        """Stop obviously repeated tool loops with the same tool and args."""
        if iteration < 1 or not tool_calls:
            return False

        latest_previous: list[ToolCall] | None = None
        seen_current_assistant = False
        for msg in reversed(messages):
            if msg.role != "assistant" or not msg.tool_calls:
                continue
            if not seen_current_assistant:
                seen_current_assistant = True
                continue
            latest_previous = msg.tool_calls
            break

        if latest_previous is None:
            return False

        if len(latest_previous) != len(tool_calls):
            return False

        for previous, current in zip(latest_previous, tool_calls, strict=False):
            if previous.name != current.name or previous.arguments != current.arguments:
                return False

        return True

    @staticmethod
    def _make_trace_message(
        *,
        role: str,
        content: str,
        turn_id: str | None,
        iteration: int | None,
        message_kind: str,
        tool_calls: list[ToolCall] | None = None,
        reasoning_content: str | None = None,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
        provider: Any = None,
        usage: Any = None,
        finish_reason: str | None = None,
        stop_reason: str | None = None,
        error: str | None = None,
        is_meta: bool = False,
    ) -> Message:
        """Build a trace message with consistent metadata."""
        return Message(
            role=role,
            content=content,
            tool_calls=tool_calls,
            reasoning_content=reasoning_content,
            tool_call_id=tool_call_id,
            turn_id=turn_id,
            iteration=iteration,
            message_kind=message_kind,
            tool_name=tool_name,
            provider=provider,
            usage=usage,
            finish_reason=finish_reason,
            stop_reason=stop_reason,
            is_meta=is_meta,
            error=error,
        )
