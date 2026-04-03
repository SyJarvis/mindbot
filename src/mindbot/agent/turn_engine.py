"""Turn engine – unified execution path for one agent turn.

Produces an **authoritative message trace** that includes every message
created during the turn: assistant messages (with or without tool_calls),
tool result messages, and the final assistant reply.  The trace is stored
on :attr:`AgentResponse.message_trace` and serves as the single source of
truth for persistence (conversation context, journal, memory).

Tool execution is routed through :class:`~mindbot.capability.facade.CapabilityFacade`
when available.  A lightweight direct-registry fallback is kept inside
the facade / backend layer for environments without a full capability stack.
"""

from __future__ import annotations

from collections.abc import Callable
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

    async def run(
        self,
        messages: list[Message],
        on_event: Callable[[AgentEvent], None] | None = None,
        turn_id: str | None = None,
    ) -> AgentResponse:
        """Run the turn until completion or a guard condition stops it.

        The returned :attr:`AgentResponse.message_trace` is the authoritative
        record of every message produced during this turn, including:

        * assistant messages with ``tool_calls`` (when tools are invoked)
        * tool result messages
        * the **final** assistant message (always present for completed turns)
        """
        response = AgentResponse(content="")
        initial_len = len(messages)

        try:
            for iteration in range(self._max_iterations):
                should_continue, messages = await self._execute_iteration(
                    messages=messages,
                    iteration=iteration,
                    on_event=on_event,
                    response=response,
                    turn_id=turn_id,
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

        # Authoritative trace: everything produced after the initial context.
        # For no-tool turns the final assistant message is appended below so
        # it always appears in the trace.
        trace = messages[initial_len:]
        if response.stop_reason == StopReason.COMPLETED and response.content:
            has_final_assistant = trace and trace[-1].role == "assistant" and not trace[-1].tool_calls
            if not has_final_assistant:
                final_msg = Message(role="assistant", content=response.content)
                messages.append(final_msg)
                trace = messages[initial_len:]

        response.message_trace = trace
        return response

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

        if llm_response.content:
            response.content += llm_response.content

        tool_calls = llm_response.tool_calls
        if not tool_calls:
            response.stop_reason = StopReason.COMPLETED
            return False, messages

        messages.append(
            Message(
                role="assistant",
                content=llm_response.content or "",
                tool_calls=tool_calls,
                reasoning_content=llm_response.reasoning_content,
            )
        )

        tool_results = await self._execute_tool_calls(
            tool_calls=tool_calls,
            on_event=on_event,
            turn_id=turn_id,
        )

        for tr in tool_results:
            messages.append(
                Message(
                    role="tool",
                    content=tr.content if tr.success else f"Error: {tr.error}",
                    tool_call_id=tr.tool_call_id,
                )
            )

        if self._has_repeated_tool_call(messages, tool_calls, iteration):
            response.stop_reason = StopReason.REPEATED_TOOL
            return False, messages

        return True, messages

    async def _execute_tool_calls(
        self,
        tool_calls: list[ToolCall],
        on_event: Callable[[AgentEvent], None] | None,
        turn_id: str | None = None,
    ) -> list[Any]:
        """Execute tool calls via CapabilityFacade (preferred) or direct registry."""
        from mindbot.context.models import ToolResult

        results: list[ToolResult] = []

        for tool_call in tool_calls:
            try:
                if on_event:
                    on_event(AgentEvent.tool_executing(tool_name=tool_call.name, call_id=tool_call.id))

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
        """Single dispatch point for tool execution.

        Tool execution always goes through the turn-scoped capability view so
        the executable set matches the tools that were exposed to the LLM.
        """
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
