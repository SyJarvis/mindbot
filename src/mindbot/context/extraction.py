"""Key information extraction from conversation messages."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mindbot.context.models import Message
from mindbot.utils import get_logger, run_sync

if TYPE_CHECKING:
    from mindbot.providers.adapter import ProviderAdapter

logger = get_logger("context.extraction")

_EXTRACT_PROMPT = """\
Extract key information from the following conversation as a concise JSON object:

{
    "entities": ["people, places, organisations mentioned"],
    "facts": ["important facts or data points"],
    "preferences": {"key": "value pairs of user preferences"},
    "actions_completed": ["actions already done"],
    "actions_pending": ["actions still to do"],
    "tools_used": ["tools that were invoked"]
}

Conversation:
{conversation}

Return ONLY valid JSON, nothing else."""


class KeyInfoExtractor:
    """Extracts structured key information from a list of messages via the LLM.

    Produces entities, facts, preferences, completed/pending actions,
    and tool usage that can be injected back into the context as a
    compact system message.
    """

    def __init__(self, llm: ProviderAdapter) -> None:
        self._llm = llm

    def extract(self, messages: list[Message]) -> Message:
        """Return a system message containing the extracted key information."""
        conversation = "\n".join(
            f"[{m.role}]: {m.text[:300]}"
            for m in messages
            if m.content
        )
        prompt = _EXTRACT_PROMPT.format(conversation=conversation)

        try:
            response = run_sync(
                self._llm.chat([Message(role="user", content=prompt)])
            )
            return Message(
                role="system",
                content=f"[Key Information]\n{response.content}",
            )
        except Exception:
            logger.warning("Key-info extraction failed; returning empty stub")
            return Message(
                role="system",
                content="[Key Information] {}",
            )
