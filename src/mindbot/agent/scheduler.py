"""Scheduler – backward-compatible build-only coordinator.

Build logic delegates to :class:`~mindbot.agent.input_builder.InputBuilder`.
Persistence has moved to
:class:`~mindbot.agent.persistence_writer.PersistenceWriter`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.mindbot.agent.input_builder import InputBuilder
from src.mindbot.context.manager import ContextManager
from src.mindbot.context.models import Message, MessageContent
from src.mindbot.utils import get_logger

if TYPE_CHECKING:
    from src.mindbot.memory.manager import MemoryManager

logger = get_logger("agent.scheduler")


class Scheduler:
    """Backward-compatible coordinator for per-turn LLM message building.

    All build methods delegate to the internal :class:`InputBuilder`.
    Persistence is handled by
    :class:`~mindbot.agent.persistence_writer.PersistenceWriter`.

    Lifecycle per turn::

        messages = scheduler.build_messages(user_input_text)
        response = await llm.chat(messages)
        # persistence is now handled by PersistenceWriter, not Scheduler
    """

    def __init__(
        self,
        context: ContextManager,
        memory: "MemoryManager | None" = None,
        *,
        memory_top_k: int = 5,
        system_prompt: str = "",
    ) -> None:
        self._input_builder = InputBuilder(
            context=context,
            memory=memory,
            memory_top_k=memory_top_k,
            system_prompt=system_prompt,
        )

    @property
    def input_builder(self) -> InputBuilder:
        """The underlying input builder used for message assembly."""
        return self._input_builder

    # ------------------------------------------------------------------
    # Build (delegated to InputBuilder)
    # ------------------------------------------------------------------

    def build_messages(
        self,
        user_input: str | MessageContent,
        *,
        session_id: str | None = None,
        intent_state: str | None = None,
    ) -> list[Message]:
        """Build the full message list for one LLM call.

        Delegates to :meth:`InputBuilder.build`.
        """
        return self._input_builder.build(
            user_input,
            session_id=session_id,
            intent_state=intent_state,
        )

    def build(
        self,
        user_input: str | MessageContent,
        *,
        session_id: str | None = None,
        intent_state: str | None = None,
    ) -> list[Message]:
        """Alias for :meth:`build_messages`."""
        return self._input_builder.build(
            user_input,
            session_id=session_id,
            intent_state=intent_state,
        )

    def assemble(
        self,
        user_input: str | MessageContent,
        *,
        session_id: str | None = None,
        intent_state: str | None = None,
    ) -> list[Message]:
        """Compatibility wrapper around :meth:`build_messages`."""
        return self._input_builder.build(
            user_input,
            session_id=session_id,
            intent_state=intent_state,
        )
