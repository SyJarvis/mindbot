"""Core data models for messages, responses, and provider info."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from typing import Any, Literal


# ---------------------------------------------------------------------------
# Multimodal content parts
# ---------------------------------------------------------------------------

@dataclass
class TextPart:
    """A text segment inside a multimodal message."""

    text: str
    type: Literal["text"] = "text"


@dataclass
class ImagePart:
    """An image segment inside a multimodal message."""

    data: bytes | str  # raw bytes, base64-encoded string, or URL
    mime_type: str = "image/png"
    type: Literal["image"] = "image"


# A message's content can be plain text or a list of multimodal parts.
MessageContent = str | list[TextPart | ImagePart]

MessageRole = Literal["system", "user", "assistant", "tool"]
MessageKind = Literal[
    "assistant_text",
    "assistant_tool_call",
    "tool_result",
    "system_injected",
    "recovery_prompt",
]


# ---------------------------------------------------------------------------
# Tool-call related models
# ---------------------------------------------------------------------------

@dataclass
class ToolCall:
    """A tool invocation requested by the LLM."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    """The result of executing a single tool call."""

    tool_call_id: str
    success: bool
    content: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# Provider information
# ---------------------------------------------------------------------------

@dataclass
class ProviderInfo:
    """Describes the provider that produced a response."""

    provider: str          # e.g. "openai", "ollama", "llama_cpp", "transformers"
    model: str             # e.g. "gpt-4o-mini"
    supports_vision: bool = False
    supports_tools: bool = False


# ---------------------------------------------------------------------------
# Chat message & response
# ---------------------------------------------------------------------------

@dataclass
class Message:
    """Unified multimodal message format used across all modules."""

    role: MessageRole
    content: MessageContent

    # Present when role == "assistant" and the LLM wants to call tools.
    tool_calls: list[ToolCall] | None = None

    # For reasoning/thinking models: optional reasoning content to resend with
    # assistant messages that have tool_calls (required by API when thinking is enabled).
    reasoning_content: str | None = None

    # Present when role == "tool" – links back to the originating ToolCall.id.
    tool_call_id: str | None = None

    # Trace metadata for persistence, observability, and recovery flows.
    turn_id: str | None = None
    iteration: int | None = None
    message_kind: MessageKind | str | None = None
    tool_name: str | None = None
    provider: ProviderInfo | dict[str, Any] | None = None
    usage: UsageInfo | dict[str, Any] | None = None
    finish_reason: str | None = None
    stop_reason: str | None = None
    is_meta: bool = False
    error: str | None = None

    # Metadata
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)
    token_count: int = 0  # estimated; filled by context manager

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    @property
    def text(self) -> str:
        """Return the plain-text representation of the content."""
        if isinstance(self.content, str):
            return self.content
        parts: list[str] = []
        for part in self.content:
            if isinstance(part, TextPart):
                parts.append(part.text)
            elif isinstance(part, ImagePart):
                parts.append("[image]")
        return "".join(parts)

    @staticmethod
    def _json_safe_dataclass(
        value: ProviderInfo | UsageInfo | dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Convert dataclass metadata to a JSON-safe dict."""
        if value is None:
            return None
        if isinstance(value, dict):
            return dict(value)
        if is_dataclass(value):
            return asdict(value)
        return None

    @property
    def provider_dict(self) -> dict[str, Any] | None:
        """Return provider metadata as a JSON-safe dict."""
        return self._json_safe_dataclass(self.provider)

    @property
    def usage_dict(self) -> dict[str, Any] | None:
        """Return usage metadata as a JSON-safe dict."""
        return self._json_safe_dataclass(self.usage)


class FinishReason(str, Enum):
    """Why the LLM stopped generating."""

    STOP = "stop"
    TOOL_CALLS = "tool_calls"
    LENGTH = "length"
    ERROR = "error"


@dataclass
class UsageInfo:
    """Token usage statistics for a single response."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class ChatResponse:
    """Unified response from any LLM provider."""

    content: str
    tool_calls: list[ToolCall] | None = None
    # For reasoning/thinking models: reasoning content to store and resend with assistant+tool_calls.
    reasoning_content: str | None = None
    provider: ProviderInfo | None = None
    finish_reason: FinishReason = FinishReason.STOP
    usage: UsageInfo | None = None
