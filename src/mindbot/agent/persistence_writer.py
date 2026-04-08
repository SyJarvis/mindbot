"""Phase C persistence writer – unified commit for one agent turn.

Consolidates the scattered persistence calls (conversation context, memory,
session journal) into a single ``commit_turn()`` entry point.  The caller
passes the user message, the :class:`~mindbot.agent.models.AgentResponse`,
and the writer takes care of the rest.

Persistence strategies:

* **conversation** – always writes the user message and final assistant
  message to the conversation block.  Intermediate tool messages are
  written according to *tool_persistence* (``none`` | ``summary`` | ``full``).
* **memory** – appends the user/assistant pair to short-term memory.
* **journal** – appends a timestamped record of the turn (including the
  full message trace) to the append-only session journal.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import TYPE_CHECKING, Literal

from mindbot.context.manager import ContextManager
from mindbot.context.models import Message
from mindbot.utils import estimate_tokens, get_logger

ToolPersistence = Literal["none", "summary", "full"]

if TYPE_CHECKING:
    from mindbot.agent.models import AgentResponse
    from mindbot.memory.manager import MemoryManager
    from mindbot.session.store import SessionJournal
    from mindbot.session.types import SessionMessage

logger = get_logger("agent.persistence_writer")


class PersistenceWriter:
    """Unified persistence entry point for a single agent turn.

    Usage::

        writer = PersistenceWriter(context, memory=mem, journal=journal)
        writer.commit_turn(
            user_text="hello",
            response=agent_response,
            session_id="default",
        )
    """

    def __init__(
        self,
        context: ContextManager,
        *,
        memory: "MemoryManager | None" = None,
        journal: "SessionJournal | None" = None,
        tool_persistence: ToolPersistence = "none",
        system_prompt: str = "",
    ) -> None:
        self._ctx = context
        self._memory = memory
        self._journal = journal
        self._tool_persistence = tool_persistence
        self._system_prompt = system_prompt
        self._journal_sessions: set[str] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def commit_turn(
        self,
        user_text: str,
        response: "AgentResponse",
        *,
        session_id: str = "default",
    ) -> None:
        """Commit one complete turn to all persistence targets.

        1. Conversation context – user + (optional tool trace) + assistant.
        2. Short-term memory – user/assistant summary.
        3. Session journal – full timestamped trace.
        """
        assistant_text = response.content or ""
        trace = response.message_trace or []

        self._commit_conversation(user_text, assistant_text, trace)
        self._commit_memory(user_text, assistant_text)
        self._commit_journal(user_text, assistant_text, trace, session_id)

    def commit_journal_turn(
        self,
        user_text: str,
        assistant_text: str,
        *,
        session_id: str = "default",
        trace: list[Message] | None = None,
    ) -> None:
        """Persist only the session journal for a completed turn."""
        self._commit_journal(user_text, assistant_text, trace or [], session_id)

    # ------------------------------------------------------------------
    # Conversation context
    # ------------------------------------------------------------------

    def _commit_conversation(
        self,
        user_text: str,
        assistant_text: str,
        trace: list[Message],
    ) -> None:
        """Write user + tool trace + assistant to the conversation block."""
        self._ctx.add_conversation_message("user", user_text)

        if trace:
            self._persist_tool_messages(trace)

        self._ctx.add_conversation_message("assistant", assistant_text)
        self._ctx.clear_user_input()
        self._ctx.clear_intent_state()

    def _persist_tool_messages(self, messages: list[Message]) -> None:
        """Write tool-related messages according to *tool_persistence*."""
        if self._tool_persistence == "none":
            return

        if self._tool_persistence == "full":
            for msg in messages:
                if msg.role == "system":
                    continue
                if msg.role == "assistant" and not msg.tool_calls:
                    continue
                self._ctx.add_conversation(msg)
            return

        # "summary" — collapse tool interactions into a single system note
        tool_names: list[str] = []
        for msg in messages:
            if msg.role == "assistant" and msg.tool_calls:
                tool_names.extend(tc.name for tc in msg.tool_calls)
        if tool_names:
            summary_text = (
                f"[Tool usage summary] Called: {', '.join(tool_names)}"
            )
            summary_msg = Message(role="system", content=summary_text)
            summary_msg.token_count = estimate_tokens(summary_msg.text)
            self._ctx.add_conversation(summary_msg)

    # ------------------------------------------------------------------
    # Short-term memory
    # ------------------------------------------------------------------

    def _commit_memory(self, user_text: str, assistant_text: str) -> None:
        """Append user/assistant pair to short-term memory."""
        if self._memory is None:
            return
        try:
            self._memory.append_to_short_term(f"User: {user_text}")
            self._memory.append_to_short_term(f"Assistant: {assistant_text}")
        except Exception:
            logger.debug("Failed to persist turn to memory")

    # ------------------------------------------------------------------
    # Session journal
    # ------------------------------------------------------------------

    def _commit_journal(
        self,
        user_text: str,
        assistant_text: str,
        trace: list[Message],
        session_id: str,
    ) -> None:
        """Append turn to the session journal (if enabled)."""
        if self._journal is None:
            return

        from mindbot.session.types import SessionMessage

        entries: list[SessionMessage] = []

        if session_id not in self._journal_sessions:
            if self._system_prompt:
                entries.append(
                    SessionMessage(role="system", content=self._system_prompt)
                )
            self._journal_sessions.add(session_id)

        entries.append(SessionMessage(role="user", content=user_text))

        if trace:
            entries.extend(self._msgs_to_journal(trace))

        # The authoritative trace already includes the final assistant
        # message when produced by TurnEngine.  Only append an explicit
        # entry when there is no trace (e.g. streaming mode).
        trace_has_final = (
            trace
            and trace[-1].role == "assistant"
            and not trace[-1].tool_calls
        )
        if not trace_has_final:
            entries.append(SessionMessage(role="assistant", content=assistant_text))

        self._journal.append(session_id, entries)

    @staticmethod
    def _msgs_to_journal(msgs: list[Message]) -> list["SessionMessage"]:
        from mindbot.session.types import SessionMessage

        result: list[SessionMessage] = []
        for m in msgs:
            tool_calls = None
            if m.tool_calls:
                tool_calls = [
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                    for tc in m.tool_calls
                ]
            result.append(
                SessionMessage(
                    role=m.role,
                    content=m.text,
                    timestamp=m.timestamp,
                    tool_calls=tool_calls,
                    tool_call_id=m.tool_call_id,
                    reasoning_content=m.reasoning_content,
                    turn_id=m.turn_id,
                    iteration=m.iteration,
                    message_kind=m.message_kind,
                    tool_name=m.tool_name,
                    provider=PersistenceWriter._json_safe_dict(m.provider),
                    usage=PersistenceWriter._json_safe_dict(m.usage),
                    finish_reason=m.finish_reason,
                    stop_reason=m.stop_reason,
                    is_meta=m.is_meta or None,
                    error=m.error,
                )
            )
        return result

    @staticmethod
    def _json_safe_dict(value: object | None) -> dict | None:
        """Convert dataclass-like metadata into plain dicts for JSONL."""
        if value is None:
            return None
        if isinstance(value, dict):
            return dict(value)
        if is_dataclass(value):
            return asdict(value)
        return None
