"""Data models for the agent subsystem."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from src.mindbot.context.models import Message, ToolCall, ToolResult

# Import approval-related enums from config to avoid circular imports
# and keep a single source of truth
from src.mindbot.config.schema import ToolSecurityLevel, ToolAskMode


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class StopReason(str, Enum):
    """Why an agent loop terminated."""

    COMPLETED = "completed"              # LLM returned text with no tool calls
    MAX_TURNS = "max_turns"              # Hit the turn limit
    LOOP_DETECTED = "loop_detected"      # Repeated identical tool calls
    REPEATED_TOOL = "repeated_tool"      # Same tool+args seen twice
    ERROR = "error"                      # Unrecoverable error
    USER_ABORTED = "user_aborted"        # User interrupted execution
    APPROVAL_DENIED = "approval_denied"  # Tool approval was denied
    APPROVAL_TIMEOUT = "approval_timeout"  # Tool approval timed out
    USER_INPUT_NEEDED = "user_input_needed"  # Waiting for user input


class AgentDecision(str, Enum):
    """Decision type made by the LLM during agent execution."""

    CONTINUE = "continue"        # Continue thinking/generating
    TOOLS = "tools"             # Needs to call tools
    USER_INPUT = "user_input"   # Needs user input
    COMPLETE = "complete"       # Task completed
    ERROR = "error"             # Error occurred


class EventType(str, Enum):
    """Types of events emitted during agent execution."""

    THINKING = "thinking"                # Agent is thinking
    DELTA = "delta"                     # Content increment (streaming)
    TOOL_CALL_REQUEST = "tool_call_request"  # Requesting tool call approval
    TOOL_CALL_APPROVED = "tool_call_approved"  # Tool call approved
    TOOL_CALL_DENIED = "tool_call_denied"      # Tool call denied
    TOOL_EXECUTING = "tool_executing"    # Executing a tool
    TOOL_RESULT = "tool_result"          # Tool execution result
    USER_INPUT_REQUEST = "user_input_request"  # Requesting user input
    USER_INPUT_RECEIVED = "user_input_received"  # User input received
    COMPLETE = "complete"                # Execution completed
    ERROR = "error"                      # Error occurred
    ABORTED = "aborted"                  # Execution aborted by user


class ApprovalDecision(str, Enum):
    """User decision for tool call approval."""

    ALLOW_ONCE = "allow_once"      # Allow this time only
    ALLOW_ALWAYS = "allow_always"  # Always allow (add to whitelist)
    DENY = "deny"                  # Deny execution


# ---------------------------------------------------------------------------
# Event Models
# ---------------------------------------------------------------------------

@dataclass
class AgentEvent:
    """Event emitted during agent execution for streaming and monitoring.

    Attributes:
        type: The type of event
        timestamp: Unix timestamp when event occurred
        data: Event-specific data
    """
    type: EventType
    timestamp: float
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def thinking(cls, turn: int = 0) -> "AgentEvent":
        """Create a thinking event."""
        return cls(type=EventType.THINKING, timestamp=time.time(), data={"turn": turn})

    @classmethod
    def delta(cls, content: str) -> "AgentEvent":
        """Create a delta event for streaming content."""
        return cls(type=EventType.DELTA, timestamp=time.time(), data={"content": content})

    @classmethod
    def tool_call_request(
        cls,
        request_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        risk_level: str = "medium",
    ) -> "AgentEvent":
        """Create a tool call request event."""
        return cls(
            type=EventType.TOOL_CALL_REQUEST,
            timestamp=time.time(),
            data={
                "request_id": request_id,
                "tool_name": tool_name,
                "arguments": arguments,
                "risk_level": risk_level,
            },
        )

    @classmethod
    def tool_call_approved(cls, request_id: str) -> "AgentEvent":
        """Create a tool call approved event."""
        return cls(type=EventType.TOOL_CALL_APPROVED, timestamp=time.time(), data={"request_id": request_id})

    @classmethod
    def tool_call_denied(cls, request_id: str, reason: str = "") -> "AgentEvent":
        """Create a tool call denied event."""
        return cls(type=EventType.TOOL_CALL_DENIED, timestamp=time.time(), data={"request_id": request_id, "reason": reason})

    @classmethod
    def tool_executing(cls, tool_name: str, call_id: str) -> "AgentEvent":
        """Create a tool executing event."""
        return cls(type=EventType.TOOL_EXECUTING, timestamp=time.time(), data={"tool_name": tool_name, "call_id": call_id})

    @classmethod
    def tool_result(cls, tool_name: str, call_id: str, result: str) -> "AgentEvent":
        """Create a tool result event."""
        return cls(
            type=EventType.TOOL_RESULT,
            timestamp=time.time(),
            data={"tool_name": tool_name, "call_id": call_id, "result": result},
        )

    @classmethod
    def user_input_request(cls, question: str, request_id: str) -> "AgentEvent":
        """Create a user input request event."""
        return cls(type=EventType.USER_INPUT_REQUEST, timestamp=time.time(), data={"question": question, "request_id": request_id})

    @classmethod
    def user_input_received(cls, input_text: str) -> "AgentEvent":
        """Create a user input received event."""
        return cls(type=EventType.USER_INPUT_RECEIVED, timestamp=time.time(), data={"input": input_text})

    @classmethod
    def complete(cls, stop_reason: StopReason) -> "AgentEvent":
        """Create a completion event."""
        return cls(type=EventType.COMPLETE, timestamp=time.time(), data={"stop_reason": stop_reason})

    @classmethod
    def error(cls, message: str) -> "AgentEvent":
        """Create an error event."""
        return cls(type=EventType.ERROR, timestamp=time.time(), data={"message": message})

    @classmethod
    def aborted(cls) -> "AgentEvent":
        """Create an aborted event."""
        return cls(type=EventType.ABORTED, timestamp=time.time())


@dataclass
class ToolApprovalRequest:
    """Request for user approval of a tool call.

    Attributes:
        request_id: Unique identifier for this request
        tool_name: Name of the tool being called
        arguments: Arguments passed to the tool
        risk_level: Risk level (low, medium, high)
        reason: Reason why approval is needed
        timeout: Timeout in seconds (default 120)
    """
    request_id: str
    tool_name: str
    arguments: dict[str, Any]
    risk_level: str = "medium"
    reason: str = ""
    timeout: float = 120


@dataclass
class InputRequest:
    """Request for user input during agent execution.

    Attributes:
        request_id: Unique identifier for this request
        question: Question to ask the user
        timeout: Timeout in seconds (default 300)
    """
    request_id: str
    question: str
    timeout: float = 300


# ---------------------------------------------------------------------------
# Step & Turn
# ---------------------------------------------------------------------------

@dataclass
class StepOutput:
    """The output of a single step (one LLM call + tool execution round)."""

    turn: int
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    llm_text: str = ""
    # For reasoning/thinking models: store and resend with assistant+tool_calls.
    reasoning_content: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TurnResult:
    """The final result returned by an agent loop."""

    final_response: str
    steps: list[StepOutput] = field(default_factory=list)
    stop_reason: StopReason = StopReason.COMPLETED
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResponse:
    """The response from an agent execution with streaming support.

    Attributes:
        content: The final text content
        events: All events emitted during execution
        stop_reason: Why execution stopped
        message_trace: Messages produced during this turn (assistant +
            tool results) in chronological order, excluding the pre-existing
            context that was passed to the orchestrator.
        metadata: Additional metadata
    """
    content: str
    events: list[AgentEvent] = field(default_factory=list)
    stop_reason: StopReason = StopReason.COMPLETED
    message_trace: list[Message] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_event(self, event: AgentEvent) -> None:
        """Add an event to the response."""
        self.events.append(event)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class LoopConfig:
    """Runtime configuration for :class:`AgentLoop`."""

    max_turns: int = 10
    max_steps_per_turn: int = 5
    loop_detection_window: int = 3  # consecutive identical-tool-call steps
    enable_auto_continue: bool = True
