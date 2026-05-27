"""Data types for Session Journal entries."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class SessionMessage:
    """One message persisted in the session journal.

    Mirrors the fields of :class:`~mindbot.context.models.Message` but
    uses only JSON-serialisable primitives so that each instance can be
    written as a single JSONL line.
    """

    role: str  # system | user | assistant | tool
    content: str
    timestamp: float = field(default_factory=time.time)
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    reasoning_content: str | None = None
    turn_id: str | None = None
    iteration: int | None = None
    message_kind: str | None = None
    tool_name: str | None = None
    provider: dict[str, Any] | None = None
    usage: dict[str, Any] | None = None
    finish_reason: str | None = None
    stop_reason: str | None = None
    is_meta: bool | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict, dropping *None* values for compactness."""
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionMessage:
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})

    def to_message(self) -> Any:
        """Convert back to :class:`~mindbot.context.models.Message` for context injection."""
        from mindbot.context.models import Message

        kwargs: dict[str, Any] = {
            "role": self.role,
            "content": self.content or "",
        }
        if self.tool_calls is not None:
            from mindbot.context.models import ToolCall
            kwargs["tool_calls"] = [ToolCall(**tc) for tc in self.tool_calls]
        for field_name in (
            "reasoning_content", "tool_call_id", "turn_id", "iteration",
            "message_kind", "tool_name", "error", "is_meta",
        ):
            val = getattr(self, field_name, None)
            if val is not None:
                kwargs[field_name] = val
        for field_name in ("provider", "usage", "finish_reason", "stop_reason"):
            val = getattr(self, field_name, None)
            if val is not None:
                kwargs[field_name] = val
        return Message(**kwargs)
