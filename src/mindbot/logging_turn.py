"""TurnLogger – records one conversation turn to turns.jsonl.

Each line in ``~/.mindbot/logs/turns.jsonl`` is a self-contained JSON object
capturing the full interaction for that turn.  The format is designed for
direct use in fine-tuning dataset pipelines::

    {
      "ts": "2026-05-03T08:30:00.123456+00:00",
      "session_id": "default",
      "turn_id": "a1b2c3d4...",
      "turn_messages": [
        {"role": "user",      "content": "..."},
        {"role": "assistant", "tool_calls": [...], "content": ""},
        {"role": "tool",      "content": "tool result"},
        {"role": "assistant", "content": "final answer"}
      ],
      "response": "final answer",
      "stop_reason": "COMPLETED"
    }

``turn_messages`` contains only the messages added during this turn
(``messages[initial_len:]``), preserving tool call / result pairs for
multi-step interactions.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _serialise_message(msg: Any) -> dict:
    """Convert a Message (or any object) to a plain JSON-serialisable dict.

    ``mode="json"`` ensures Pydantic recursively converts nested models,
    enums, and custom types to JSON-native primitives.
    """
    if hasattr(msg, "model_dump"):
        return msg.model_dump(mode="json", exclude_none=True)
    if hasattr(msg, "__dict__"):
        return {k: v for k, v in vars(msg).items() if v is not None}
    return {"content": str(msg)}


def _json_fallback(obj: Any) -> Any:
    """Fallback encoder for types that slip past _serialise_message."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if hasattr(obj, "__dict__"):
        return vars(obj)
    return str(obj)


class TurnLogger:
    """Append one JSONL record per turn to ``~/.mindbot/logs/turns.jsonl``."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (Path.home() / ".mindbot" / "logs" / "turns.jsonl")

    def log_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        turn_messages: list[Any],
        response: str,
        stop_reason: str,
    ) -> None:
        """Append one turn record.  Never raises — errors are logged and swallowed."""
        record = {
            "ts": datetime.now(UTC).isoformat(),
            "session_id": session_id,
            "turn_id": turn_id,
            "turn_messages": [_serialise_message(m) for m in turn_messages],
            "response": response,
            "stop_reason": stop_reason,
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False, default=_json_fallback) + "\n")
        except Exception:
            from mindbot.logging import logger

            logger.exception(
                "TurnLogger: failed to write turn record turn_id={}", turn_id
            )


_TURN_LOGGER: TurnLogger | None = None


def get_turn_logger() -> TurnLogger:
    """Return the process-level singleton TurnLogger."""
    global _TURN_LOGGER
    if _TURN_LOGGER is None:
        _TURN_LOGGER = TurnLogger()
    return _TURN_LOGGER
