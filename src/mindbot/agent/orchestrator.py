"""Agent orchestrator - unified entry point for agent execution.

This module provides the orchestrator that coordinates:
- LLM calls with streaming support
- Tool execution with approval workflow
- User input requests
- Interrupt handling
- Decision making (continue/tools/user_input/complete)

The orchestrator enables the agent to autonomously decide how to respond
based on the LLM's output.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from mindbot.agent.approval import ApprovalManager
from mindbot.config.schema import ToolApprovalConfig
from mindbot.agent.input import InputManager
from mindbot.agent.interrupt import AgentExecution, InterruptException
from mindbot.agent.models import (
    AgentDecision,
    AgentEvent,
    AgentResponse,
    StopReason,
)
from mindbot.agent.streaming import StreamingExecutor
from mindbot.context.models import ChatResponse, Message, ToolCall
from mindbot.providers.adapter import ProviderAdapter
from mindbot.capability.backends.tooling.models import Tool
from mindbot.utils import get_logger

# TYPE_CHECKING import keeps the capability layer an optional dependency during
# Phase 1; the orchestrator still defaults to the existing ToolRegistry path.
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from mindbot.capability.facade import CapabilityFacade

logger = get_logger("agent.orchestrator")


class AgentOrchestrator:
    """Unified orchestrator for agent execution with autonomous decision making.

    The orchestrator:
    1. Executes the LLM in a streaming manner
    2. Detects the LLM's decision (tools/user_input/complete)
    3. Coordinates tool approvals and execution
    4. Handles user input requests
    5. Supports user interrupts

    Usage:
        orchestrator = AgentOrchestrator(
            llm=llm_adapter,
            tools=tool_list,
            approval_config=approval_config,
        )

        response = await orchestrator.chat(
            message="What's the weather like?",
            session_id="user123",
            on_event=lambda e: print(f"Event: {e.type}"),
        )
    """

    def __init__(
        self,
        llm: ProviderAdapter,
        tools: list[Tool] | None = None,
        approval_config: ToolApprovalConfig | None = None,
        max_iterations: int = 20,
        capability_facade: "CapabilityFacade | None" = None,
    ) -> None:
        """Initialize the orchestrator.

        Args:
            llm: The provider adapter for LLM calls
            tools: Available tools for the agent
            approval_config: Tool approval configuration
            max_iterations: Maximum tool iterations per request
            capability_facade: Optional CapabilityFacade injected for Phase 2+
                capability-layer execution.  When *None* (default) the
                orchestrator falls back to the current ToolRegistry path so
                that existing behaviour is completely unchanged.
        """
        self._llm = llm
        self._tools = tools or []
        self._max_iterations = max_iterations
        # Phase 1: store for future use; not yet wired into the hot path.
        self._capability_facade = capability_facade

        # Initialize components
        self._streaming_executor = StreamingExecutor(llm)

        # Bind tools to LLM
        if self._tools:
            self._llm_with_tools = llm.bind_tools(tools)
        else:
            self._llm_with_tools = llm

        # Approval and input managers
        self._approval_config = approval_config or ToolApprovalConfig()
        self._approval_manager = ApprovalManager(self._approval_config)
        self._input_manager = InputManager()

    async def chat(
        self,
        messages: list[Message],
        on_event: Callable[[AgentEvent], None] | None = None,
        execution: AgentExecution | None = None,
        turn_id: str | None = None,  # Add turn_id parameter
    ) -> AgentResponse:
        """Execute agent with autonomous decision making.

        This is the unified entry point that:
        1. Streams the LLM response
        2. Detects if tools are needed
        3. Requests approval if required
        4. Executes tools
        5. Continues until complete or max iterations

        Args:
            messages: Conversation messages including user input
            on_event: Optional callback for real-time events
            execution: Optional execution session for interrupt support

        Returns:
            AgentResponse with content, events, and stop_reason
        """
        execution = execution or AgentExecution()
        response = AgentResponse(content="")
        initial_len = len(messages)

        try:
            # Main execution loop
            for iteration in range(self._max_iterations):
                # Check for interrupt
                if await execution.check_interrupted():
                    response.stop_reason = StopReason.USER_ABORTED
                    if on_event:
                        on_event(AgentEvent.aborted())
                    break

                # Execute one iteration (LLM + optional tools)
                should_continue, messages = await self._execute_iteration(
                    messages=messages,
                    iteration=iteration,
                    on_event=on_event,
                    response=response,
                    execution=execution,
                    turn_id=turn_id,
                )

                if not should_continue:
                    break

            # Send completion event
            if on_event and response.stop_reason == StopReason.COMPLETED:
                on_event(AgentEvent.complete(response.stop_reason))

        except InterruptException:
            response.stop_reason = StopReason.USER_ABORTED
            if on_event:
                on_event(AgentEvent.aborted())

        except Exception as e:
            logger.error(f"Error in agent execution: {e}")
            response.stop_reason = StopReason.ERROR
            if on_event:
                on_event(AgentEvent.error(str(e)))

        response.message_trace = messages[initial_len:]
        return response

    async def _execute_iteration(
        self,
        messages: list[Message],
        iteration: int,
        on_event: Callable[[AgentEvent], None] | None,
        response: AgentResponse,
        execution: AgentExecution,
        turn_id: str | None = None,
    ) -> tuple[bool, list[Message]]:
        """Execute a single iteration (LLM call + tool execution).

        Returns:
            (should_continue, updated_messages)
        """
        # Call LLM with streaming
        llm_response = await self._streaming_executor.execute_stream(
            messages=messages,
            on_event=on_event,
            tools=self._tools,
        )

        # Accumulate content
        if llm_response.content:
            response.content += llm_response.content

        # Check for tool calls
        tool_calls = llm_response.tool_calls

        if not tool_calls:
            # No tools - task complete
            response.stop_reason = StopReason.COMPLETED
            return False, messages

        # Append assistant message with tool calls (include reasoning_content for thinking models)
        messages.append(
            Message(
                role="assistant",
                content=llm_response.content or "",
                tool_calls=tool_calls,
                reasoning_content=llm_response.reasoning_content,
            )
        )

        # Execute tool calls with approval
        tool_results = await self._execute_tool_calls(
            tool_calls=tool_calls,
            on_event=on_event,
            execution=execution,
            turn_id=turn_id,  # Pass turn_id for tracing
        )

        # Check if any tool was denied
        for result in tool_results:
            if not result.success and "approval" in result.error.lower():
                response.stop_reason = StopReason.APPROVAL_DENIED
                return False, messages

        # Append tool results
        for tr in tool_results:
            messages.append(
                Message(
                    role="tool",
                    content=tr.content if tr.success else f"Error: {tr.error}",
                    tool_call_id=tr.tool_call_id,
                )
            )

        # Check for interrupt after tools
        if await execution.check_interrupted():
            response.stop_reason = StopReason.USER_ABORTED
            if on_event:
                on_event(AgentEvent.aborted())
            return False, messages

        # Continue to next iteration
        return True, messages

    async def _execute_tool_calls(
        self,
        tool_calls: list[ToolCall],
        on_event: Callable[[AgentEvent], None] | None,
        execution: AgentExecution,
        turn_id: str | None = None,
    ) -> list[Any]:
        """Execute tool calls with approval workflow.

        Args:
            tool_calls: List of tool calls to execute
            on_event: Optional callback for real-time events
            execution: Execution session for interrupt support
            turn_id: Optional turn ID for logging

        Returns:
            List of tool results
        """
        from mindbot.context.models import ToolResult

        results: list[ToolResult] = []

        for tool_call in tool_calls:
            # Check for interrupt
            if await execution.check_interrupted():
                break

            # Request approval
            try:
                decision = await self._approval_manager.request_approval(
                    tool_name=tool_call.name,
                    arguments=tool_call.arguments,
                    on_event=on_event,
                )

                if decision == "deny":
                    if on_event:
                        on_event(AgentEvent.tool_call_denied(
                            request_id=tool_call.id,
                            reason="User denied approval",
                        ))
                    results.append(
                        ToolResult(
                            tool_call_id=tool_call.id,
                            success=False,
                            error="Tool call was denied by user",
                        )
                    )
                    continue

                if on_event:
                    on_event(AgentEvent.tool_call_approved(request_id=tool_call.id))
                    on_event(AgentEvent.tool_executing(
                        tool_name=tool_call.name,
                        call_id=tool_call.id,
                    ))

            except asyncio.TimeoutError:
                if on_event:
                    on_event(AgentEvent.tool_call_denied(
                        request_id=tool_call.id,
                        reason="Approval timed out",
                    ))
                results.append(
                    ToolResult(
                        tool_call_id=tool_call.id,
                        success=False,
                        error="Approval request timed out",
                    )
                )
                continue

            # Execute tool
            try:
                # Import here to avoid circular dependency
                from mindbot.capability.backends.tooling.executor import ToolExecutor
                from mindbot.capability.backends.tooling.registry import ToolRegistry

                registry = ToolRegistry.from_tools(self._tools)
                executor = ToolExecutor(registry)

                tool_results = await executor.execute_batch([tool_call])
                results.extend(tool_results)

                if on_event and tool_results:
                    on_event(AgentEvent.tool_result(
                        tool_name=tool_call.name,
                        call_id=tool_call.id,
                        result=tool_results[0].content if tool_results[0].success else tool_results[0].error,
                    ))

            except Exception as e:
                logger.error(f"Error executing tool {tool_call.name}: {e}")
                if on_event:
                    on_event(AgentEvent.error(f"Tool execution error: {e}"))
                results.append(
                    ToolResult(
                        tool_call_id=tool_call.id,
                        success=False,
                        error=str(e),
                    )
                )

        return results

    def request_user_input(
        self,
        question: str,
        on_event: Callable[[AgentEvent], None] | None = None,
    ) -> asyncio.Task[str]:
        """Request user input (returns task for async waiting).

        This is a non-blocking way to request input. The caller can
        await the returned task to get the user's response.

        Args:
            question: The question to ask
            on_event: Optional event callback

        Returns:
            Task that resolves to the user's input
        """
        return asyncio.create_task(
            self._input_manager.request_input(question, on_event)
        )

    def provide_input(self, request_id: str, input_text: str) -> None:
        """Provide input for a pending request.

        Args:
            request_id: The request ID from the USER_INPUT_REQUEST event
            input_text: The user's input
        """
        self._input_manager.provide_input(request_id, input_text)

    def resolve_approval(
        self,
        request_id: str,
        decision: str,  # "allow_once", "allow_always", "deny"
    ) -> None:
        """Resolve a pending tool approval request.

        Args:
            request_id: The request ID from the TOOL_CALL_REQUEST event
            decision: The user's decision
        """
        from mindbot.agent.models import ApprovalDecision

        self._approval_manager.resolve(
            request_id,
            ApprovalDecision(decision),
        )

    @property
    def approval_config(self) -> ToolApprovalConfig:
        """Get the approval configuration."""
        return self._approval_config

    def add_tool_to_whitelist(self, tool_name: str, pattern: str = ".*") -> None:
        """Add a tool to the whitelist.

        Args:
            tool_name: Name of the tool
            pattern: Regex pattern for arguments (default: all)
        """
        self._approval_manager.add_to_whitelist(tool_name, pattern)

    def remove_tool_from_whitelist(self, tool_name: str) -> None:
        """Remove a tool from the whitelist.

        Args:
            tool_name: Name of the tool
        """
        self._approval_manager.remove_from_whitelist(tool_name)
