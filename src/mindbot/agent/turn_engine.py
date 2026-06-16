"""Turn engine – unified execution path for one agent turn.

提供两种接口：
1. run() → AgentResponse：完整执行后返回（供 chat() 使用）
2. run_stream() → AsyncIterator[str]：逐 token yield（供 chat_stream() 使用）
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, Any

from mindbot.agent.models import AgentEvent, AgentResponse, EventType, RuntimeRequest, StopReason
from mindbot.agent.streaming import StreamingExecutor
from mindbot.context.models import Message, ToolCall
from mindbot.logging import logger, set_log_context
from mindbot.logging_turn import get_turn_logger
from mindbot.providers.adapter import ProviderAdapter

if TYPE_CHECKING:
    from mindbot.capability.facade import CapabilityFacade
    from mindbot.capability.backends.tooling.models import Tool


class TurnEngine:
    """Execute one complete agent turn using a single shared loop."""

    def __init__(
        self,
        llm: ProviderAdapter,
        tools: list["Tool"] | None = None,
        *,
        max_iterations: int = 20,
        task_progress_policy: str = "ask",
        task_progress_review_after: int | None = 15,
        capability_facade: "CapabilityFacade | None" = None,
    ) -> None:
        self._llm = llm
        self._tools = tools or []
        self._max_iterations = max_iterations
        self._task_progress_policy = task_progress_policy
        self._task_progress_review_after = task_progress_review_after
        self._capability_facade = capability_facade
        self._streaming_executor = StreamingExecutor(llm)
        self._last_stream_response: AgentResponse | None = None
        self._last_event_response: AgentResponse | None = None

    # ------------------------------------------------------------------
    # 非流式接口（供 chat() 使用）
    # ------------------------------------------------------------------

    async def run(
        self,
        messages: list[Message],
        on_event: Callable[[AgentEvent], None] | None = None,
        on_user_input_request: Callable[[str, str], Awaitable[str]] | None = None,
        on_runtime_request: Callable[[RuntimeRequest], Awaitable[str]] | None = None,
        on_pending_user_input: Callable[[], Awaitable[list[str]]] | None = None,
        turn_id: str | None = None,
    ) -> AgentResponse:
        """完整执行 turn，返回 AgentResponse。"""
        async for event in self.run_events(
            messages,
            on_user_input_request=on_user_input_request,
            on_runtime_request=on_runtime_request,
            on_pending_user_input=on_pending_user_input,
            turn_id=turn_id,
        ):
            if on_event:
                on_event(event)
        if self._last_event_response is None:
            raise RuntimeError("run_events() ended without a response")
        return self._last_event_response

    # ------------------------------------------------------------------
    # 流式接口（供 chat_stream() 使用）
    # ------------------------------------------------------------------

    async def run_stream(
        self,
        messages: list[Message],
        on_event: Callable[[AgentEvent], None] | None = None,
        on_user_input_request: Callable[[str, str], Awaitable[str]] | None = None,
        on_runtime_request: Callable[[RuntimeRequest], Awaitable[str]] | None = None,
        on_pending_user_input: Callable[[], Awaitable[list[str]]] | None = None,
        turn_id: str | None = None,
    ) -> AsyncIterator[str]:
        """逐 token 流式执行 turn。

        工具迭代期间不 yield（工具调用需要完整响应），
        最终文本迭代逐 token yield。

        流结束后通过 last_stream_response 属性获取完整 AgentResponse。
        """
        async for event in self.run_events(
            messages,
            on_user_input_request=on_user_input_request,
            on_runtime_request=on_runtime_request,
            on_pending_user_input=on_pending_user_input,
            turn_id=turn_id,
        ):
            if on_event:
                on_event(event)
            if event.type == EventType.DELTA:
                content = event.data.get("content", "")
                if content:
                    yield content
        if self._last_event_response is None:
            raise RuntimeError("run_events() ended without a response")
        self._last_stream_response = self._last_event_response

    async def run_events(
        self,
        messages: list[Message],
        on_user_input_request: Callable[[str, str], Awaitable[str]] | None = None,
        on_runtime_request: Callable[[RuntimeRequest], Awaitable[str]] | None = None,
        on_pending_user_input: Callable[[], Awaitable[list[str]]] | None = None,
        turn_id: str | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Execute one turn and yield canonical AgentEvents as they happen."""
        resolved_turn_id = turn_id or uuid.uuid4().hex
        set_log_context(turn_id=resolved_turn_id)

        response = AgentResponse(content="")
        response.metadata["turn_id"] = resolved_turn_id
        initial_len = len(messages)
        t0 = time.monotonic()

        self._last_event_response = None

        logger.debug("turn.start(events) turn_id={} messages={} tools={}", resolved_turn_id, initial_len, len(self._tools))

        seq = 0

        def stamp(event: AgentEvent) -> AgentEvent:
            nonlocal seq
            seq += 1
            return event.with_runtime_context(resolved_turn_id, seq)

        runtime_request_resolver = on_runtime_request
        if runtime_request_resolver is None and on_user_input_request is not None:
            async def runtime_request_resolver(request: RuntimeRequest) -> str:
                return await on_user_input_request(request.prompt, request.request_id)

        try:
            progress_review_requested = False
            for iteration in range(self._max_iterations):
                yield stamp(AgentEvent.thinking())

                logger.debug("llm.request.start turn_id={} iteration={}", resolved_turn_id, iteration)
                async for chunk in self._streaming_executor.stream(
                    messages, tools=self._tools,
                ):
                    if chunk:
                        yield stamp(AgentEvent.delta(chunk))

                llm_response = self._streaming_executor.last_chat_response
                tool_calls = llm_response.tool_calls

                if not tool_calls and llm_response.content:
                    text_calls = self._detect_text_tool_calls(llm_response.content)
                    if text_calls and self._tools:
                        available = {t.name for t in self._tools}
                        detected = []
                        for name, args in text_calls:
                            if name in available:
                                detected.append(ToolCall(
                                    id=f"text_tc_{uuid.uuid4().hex[:8]}",
                                    name=name,
                                    arguments=args,
                                ))
                        if detected:
                            import re
                            clean = re.sub(r'\{\s*"name"\s*:\s*"[^"]*"\s*,\s*"arguments"\s*:\s*\{[\s\S]*?\}\s*\}', '', llm_response.content).strip()
                            llm_response.content = clean
                            tool_calls = detected
                            logger.info("tool_calls.detected(text) turn_id={} iteration={} tools={}",
                                        resolved_turn_id, iteration, [tc.name for tc in detected])

                logger.debug(
                    "llm.response.received turn_id={} iteration={} tool_calls={} content_len={}",
                    resolved_turn_id, iteration, len(tool_calls or []), len(llm_response.content or ""),
                )

                if not tool_calls:
                    # 最终文本回复：逐 token yield
                    response.content = llm_response.content or ""
                    response.metadata["final_message_metadata"] = {
                        "provider": llm_response.provider,
                        "usage": llm_response.usage,
                        "finish_reason": getattr(llm_response.finish_reason, "value", llm_response.finish_reason),
                    }
                    response.stop_reason = StopReason.COMPLETED
                    yield stamp(AgentEvent.complete(response.stop_reason))
                    break

                # 工具调用：构建 trace，执行工具
                logger.debug("tool_calls.detected turn_id={} iteration={} tools={}", resolved_turn_id, iteration, [tc.name for tc in tool_calls])
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

                tool_event_queue: asyncio.Queue[AgentEvent] = asyncio.Queue()
                tool_task = asyncio.create_task(self._execute_tool_calls(
                    tool_calls=tool_calls,
                    on_event=tool_event_queue.put_nowait,
                    turn_id=resolved_turn_id,
                    iteration=iteration,
                ))
                while not tool_task.done():
                    try:
                        yield stamp(await asyncio.wait_for(tool_event_queue.get(), timeout=0.01))
                    except asyncio.TimeoutError:
                        continue
                while not tool_event_queue.empty():
                    yield stamp(tool_event_queue.get_nowait())
                tool_results = await tool_task

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
                if self._should_request_task_review(iteration) and not progress_review_requested:
                    progress_review_requested = True
                    question = self._task_review_prompt(iteration + 1)
                    request_id = f"review-task-progress-{resolved_turn_id}"
                    request = RuntimeRequest.user_input(
                        request_id=request_id,
                        prompt=question,
                        metadata={
                            "reason": "task_progress_review",
                            "iteration": iteration,
                            "review_after": self._task_progress_review_after,
                        },
                    )
                    yield stamp(AgentEvent.user_input_request(
                        question,
                        request_id=request_id,
                        request=request,
                    ))
                    if runtime_request_resolver is None:
                        response.stop_reason = StopReason.USER_INPUT_NEEDED
                        response.content = question
                        break
                    answer = await runtime_request_resolver(request)
                    yield stamp(AgentEvent.user_input_received(answer))
                    messages.append(
                        self._make_trace_message(
                            role="user",
                            content=answer,
                            turn_id=resolved_turn_id,
                            iteration=iteration,
                            message_kind="user_input",
                        )
                    )
                    continue
                async for event in self._append_pending_user_input(
                    messages,
                    on_pending_user_input,
                    resolved_turn_id,
                    iteration,
                ):
                    yield stamp(event)
            else:
                response.stop_reason = StopReason.MAX_TURNS

            if response.stop_reason not in (StopReason.COMPLETED, StopReason.ERROR):
                yield stamp(AgentEvent.complete(response.stop_reason))

        except Exception as exc:
            logger.exception("turn.error(events) turn_id={}", resolved_turn_id)
            response.stop_reason = StopReason.ERROR
            yield stamp(AgentEvent.error(str(exc)))

        elapsed = time.monotonic() - t0
        logger.info(
            "turn.finish(events) turn_id={} stop_reason={} elapsed={:.3f}s",
            resolved_turn_id, response.stop_reason, elapsed,
        )

        self._build_trace(messages, initial_len, response, resolved_turn_id)
        self._write_turn_record(messages, initial_len, response, resolved_turn_id)
        self._last_event_response = response

    async def _append_pending_user_input(
        self,
        messages: list[Message],
        on_pending_user_input: Callable[[], Awaitable[list[str]]] | None,
        turn_id: str,
        iteration: int,
    ) -> AsyncIterator[AgentEvent]:
        if on_pending_user_input is None:
            return
        pending_inputs = await on_pending_user_input()
        for input_text in pending_inputs:
            yield AgentEvent.user_input_received(input_text)
            messages.append(
                self._make_trace_message(
                    role="user",
                    content=input_text,
                    turn_id=turn_id,
                    iteration=iteration,
                    message_kind="user_input",
                )
            )

    @property
    def last_stream_response(self) -> AgentResponse:
        """run_stream() 结束后的完整 AgentResponse。"""
        if self._last_stream_response is None:
            raise RuntimeError("last_stream_response not available until run_stream() completes")
        return self._last_stream_response

    # ------------------------------------------------------------------
    # 非流式迭代
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Text-based tool call detection
    # ------------------------------------------------------------------

    _TOOL_CALL_RE: Any = None  # compiled regex, lazy init

    @classmethod
    def _detect_text_tool_calls(cls, content: str) -> list[tuple[str, dict]]:
        """Detect tool calls embedded in LLM text output.

        Some models output tool calls as JSON text instead of using the
        structured function calling API.  This method finds patterns like::

            {"name": "tool_name", "arguments": {...}}

        Returns a list of (tool_name, arguments_dict) tuples.
        """
        import json
        import re

        if cls._TOOL_CALL_RE is None:
            cls._TOOL_CALL_RE = re.compile(r'\{\s*"name"\s*:')

        results = []
        for m in cls._TOOL_CALL_RE.finditer(content):
            start = m.start()
            # Try to parse valid JSON starting from this position
            for end in range(len(content), start, -1):
                candidate = content[start:end]
                try:
                    obj = json.loads(candidate)
                    if isinstance(obj, dict) and "name" in obj and "arguments" in obj:
                        results.append((obj["name"], obj["arguments"] if isinstance(obj["arguments"], dict) else {}))
                        break
                except (json.JSONDecodeError, ValueError):
                    continue
        return results

    # ------------------------------------------------------------------
    # Iteration
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
        logger.debug("llm.request.start turn_id={} iteration={} messages={}", turn_id, iteration, len(messages))
        llm_response = await self._streaming_executor.execute_stream(
            messages=messages,
            on_event=on_event,
            tools=self._tools,
        )
        logger.debug(
            "llm.response.received turn_id={} iteration={} tool_calls={} content_len={}",
            turn_id, iteration, len(llm_response.tool_calls or []), len(llm_response.content or ""),
        )

        tool_calls = llm_response.tool_calls

        # Fallback: detect tool calls in text for models that don't support
        # structured function calling (e.g. GLM, some Qwen variants).
        if not tool_calls and llm_response.content:
            text_calls = self._detect_text_tool_calls(llm_response.content)
            if text_calls and self._tools:
                # Check detected names against available tools
                available = {t.name for t in self._tools}
                from mindbot.context.models import ToolCall
                detected = []
                for name, args in text_calls:
                    if name in available:
                        detected.append(ToolCall(
                            id=f"text_tc_{uuid.uuid4().hex[:8]}",
                            name=name,
                            arguments=args,
                        ))
                if detected:
                    # Strip the tool call JSON blocks from displayed content
                    import re
                    clean = re.sub(r'\{\s*"name"\s*:\s*"[^"]*"\s*,\s*"arguments"\s*:\s*\{[\s\S]*?\}\s*\}', '', llm_response.content).strip()
                    llm_response.content = clean
                    tool_calls = detected
                    logger.info("tool_calls.detected(text) turn_id={} iteration={} tools={}",
                                turn_id, iteration, [tc.name for tc in detected])

        if not tool_calls:
            response.content = llm_response.content or ""
            response.metadata["final_message_metadata"] = {
                "provider": llm_response.provider,
                "usage": llm_response.usage,
                "finish_reason": getattr(llm_response.finish_reason, "value", llm_response.finish_reason),
            }
            response.stop_reason = StopReason.COMPLETED
            return False, messages

        logger.debug("tool_calls.detected turn_id={} iteration={} tools={}", turn_id, iteration, [tc.name for tc in tool_calls])

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

        if self._should_request_task_review(iteration):
            response.stop_reason = StopReason.USER_INPUT_NEEDED
            response.content = self._task_review_prompt(iteration + 1)
            if on_event:
                on_event(AgentEvent.user_input_request(
                    response.content,
                    request_id=f"review-task-progress-{turn_id or uuid.uuid4().hex}",
                ))
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
            t0 = time.monotonic()
            logger.debug("tool.start turn_id={} tool={} call_id={}", turn_id, tool_call.name, tool_call.id)
            try:
                if on_event:
                    on_event(AgentEvent.tool_executing(
                        tool_name=tool_call.name,
                        call_id=tool_call.id,
                        arguments=tool_call.arguments,
                    ))
                    await asyncio.sleep(0)

                tool_result = await self._resolve_and_execute(tool_call, turn_id)
                results.append(tool_result)
                elapsed = time.monotonic() - t0

                logger.debug(
                    "tool.finish turn_id={} tool={} call_id={} success={} elapsed={:.3f}s",
                    turn_id, tool_call.name, tool_call.id, tool_result.success, elapsed,
                )
                if on_event:
                    on_event(
                        AgentEvent.tool_result(
                            tool_name=tool_call.name,
                            call_id=tool_call.id,
                            result=tool_result.content if tool_result.success else tool_result.error,
                        )
                    )

            except Exception as exc:
                elapsed = time.monotonic() - t0
                logger.exception(
                    "tool.error turn_id={} tool={} call_id={} elapsed={:.3f}s",
                    turn_id, tool_call.name, tool_call.id, elapsed,
                )
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
    # Trace 构建 & JSONL 写入
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

    def _write_turn_record(
        self,
        messages: list[Message],
        initial_len: int,
        response: AgentResponse,
        turn_id: str,
    ) -> None:
        """Write one JSONL record to turns.jsonl for fine-tuning data collection."""
        from mindbot.logging import _session_id_var  # noqa: PLC0415

        turn_messages = messages[initial_len:]
        if not turn_messages:
            return

        get_turn_logger().log_turn(
            session_id=_session_id_var.get(),
            turn_id=turn_id,
            turn_messages=turn_messages,
            response=response.content,
            stop_reason=response.stop_reason.value if response.stop_reason else "UNKNOWN",
        )

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

    def _should_request_task_review(self, iteration: int) -> bool:
        if self._task_progress_policy != "ask":
            return False
        review_after = self._task_progress_review_after
        if review_after is None:
            return False
        completed_iterations = iteration + 1
        return completed_iterations >= review_after

    def _task_review_prompt(self, completed_iterations: int) -> str:
        return (
            f"I have completed {completed_iterations} tool-backed step(s), "
            "but the task still appears to need more work. Please review the "
            "current progress and confirm whether I should continue, change "
            "approach, or stop here."
        )

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
