"""Archive old conversation messages into the memory system."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from src.mindbot.context.models import Message
from src.mindbot.utils import get_logger

if TYPE_CHECKING:
    from src.mindbot.memory.manager import MemoryManager

logger = get_logger("context.archiver")


class MemoryArchiver:
    """Moves conversation messages into long-term memory and returns a reference.

    This lets the context window stay compact while preserving the full
    conversation in the searchable memory store.
    """

    def __init__(self, memory: MemoryManager) -> None:
        self._memory = memory

    def archive(self, messages: list[Message]) -> tuple[str, Message]:
        """Archive *messages* and return ``(archive_id, reference_message)``.

        The reference message is a lightweight system message that records
        the archive ID so the LLM can request retrieval if needed.
        """
        archive_id = uuid.uuid4().hex[:8]
        content = "\n".join(f"[{m.role}]: {m.text}" for m in messages)
        self._memory.promote_to_long_term(
            content=f"[Archived {archive_id}]\n{content}",
            metadata={"type": "archive", "message_count": len(messages)},
        )
        logger.info("Archived %d messages (id=%s)", len(messages), archive_id)
        ref_msg = Message(
            role="system",
            content=(
                f"[Archived conversation (id: {archive_id}). "
                f"Use memory search to retrieve if needed.]"
            ),
        )
        return archive_id, ref_msg
