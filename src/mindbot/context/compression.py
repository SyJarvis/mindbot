"""Context compression strategies.

Strategies operate on the **conversation** block only.  The caller
(``ContextManager.compact``) passes in the conversation messages and the
block's token budget as ``target_tokens``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from mindbot.context.models import Message
from mindbot.utils import estimate_tokens
from mindbot.logging import logger

if TYPE_CHECKING:
    from mindbot.memory.manager import MemoryManager
    from mindbot.providers.adapter import ProviderAdapter


# ===================================================================
# Base
# ===================================================================

class CompressionStrategy(ABC):
    """Base class for context compression strategies."""

    @abstractmethod
    async def compress(self, messages: list[Message], target_tokens: int) -> list[Message]:
        """Return a compressed copy of *messages* that fits within *target_tokens*."""


# ===================================================================
# Truncate
# ===================================================================

_DROP_PRIORITIES: dict[str, int] = {
    "tool_result": 0,
    "assistant_tool_call": 1,
}


def _drop_priority(msg: Message) -> int:
    kind = getattr(msg, "message_kind", None) or ""
    return _DROP_PRIORITIES.get(kind, 10)


class TruncateStrategy(CompressionStrategy):
    """Drop low-value messages first, then truncate from the oldest end.

    Phase 1 – drop messages by ascending drop-priority (tool_result
    first, then assistant_tool_call pairs) until the remaining messages
    fit within the budget or only high-value messages remain.

    Phase 2 – if still over budget, drop the oldest non-system messages
    until the budget is met.
    """

    async def compress(self, messages: list[Message], target_tokens: int) -> list[Message]:
        return _truncate_messages_sync(messages, target_tokens)


# ===================================================================
# Summarize
# ===================================================================

class SummarizeStrategy(CompressionStrategy):
    """Summarize older messages via the LLM, keeping recent ones verbatim.

    Uses the LLM to generate a summary of older messages, preserving key
    facts, decisions, and tool results.  Falls back to :class:`TruncateStrategy`
    if the LLM call fails.
    """

    def __init__(self, llm: ProviderAdapter, recent_keep: int = 4) -> None:
        self._llm = llm
        self._recent_keep = recent_keep

    async def compress(self, messages: list[Message], target_tokens: int) -> list[Message]:
        if len(messages) <= self._recent_keep + 1:
            return list(messages)

        system = [m for m in messages if m.role == "system"]
        non_system = [m for m in messages if m.role != "system"]

        to_summarize = non_system[: -self._recent_keep]
        to_keep = non_system[-self._recent_keep:]

        text_block = "\n".join(f"[{m.role}]: {m.text}" for m in to_summarize)
        summary_prompt = (
            "Summarize the following conversation concisely, preserving key "
            "facts, decisions, and tool results:\n\n" + text_block
        )

        try:
            response = await self._llm.chat(
                [Message(role="user", content=summary_prompt)]
            )
            summary_msg = Message(
                role="system",
                content=f"[Conversation summary] {response.content}",
            )
        except Exception:
            logger.warning("Summarize failed; falling back to truncation")
            return await TruncateStrategy().compress(messages, target_tokens)

        return system + [summary_msg] + to_keep


# ===================================================================
# Rolling Summarize
# ===================================================================

_SUMMARY_MARKER = "[Rolling summary]"


class RollingSummarizeStrategy(CompressionStrategy):
    """Incremental summary that updates an existing summary instead of
    re-processing from scratch each time.

    After the first compression the conversation block contains a marker
    message whose text starts with ``[Rolling summary]``.  On subsequent
    compressions the strategy detects this marker, extracts the previous
    summary, and only asks the LLM to *update* it with newly-graduated
    messages.  When the summary grows beyond *max_summary_tokens* a
    condensation step automatically shrinks it.

    Falls back to :class:`TruncateStrategy` if the LLM call fails.
    """

    def __init__(
        self,
        llm: ProviderAdapter,
        recent_keep: int = 4,
        max_summary_tokens: int = 800,
    ) -> None:
        self._llm = llm
        self._recent_keep = recent_keep
        self._max_summary_tokens = max_summary_tokens

    async def compress(self, messages: list[Message], target_tokens: int) -> list[Message]:
        if len(messages) <= self._recent_keep + 1:
            return list(messages)

        system, prev_summary, non_summary = _partition_by_marker(messages)

        if len(non_summary) <= self._recent_keep:
            return list(messages)

        to_summarize = non_summary[: -self._recent_keep]
        to_keep = non_summary[-self._recent_keep:]

        new_text = _format_messages(to_summarize)

        try:
            updated = await self._update_summary(prev_summary, new_text)
        except Exception:
            logger.warning("RollingSummarize failed; falling back to truncation")
            return await TruncateStrategy().compress(messages, target_tokens)

        if estimate_tokens(updated) > self._max_summary_tokens:
            updated = await self._condense(updated)

        summary_msg = Message(
            role="system",
            content=f"{_SUMMARY_MARKER} {updated}",
        )
        return system + [summary_msg] + to_keep

    async def _update_summary(self, prev: str, new_text: str) -> str:
        if prev:
            prompt = (
                "Existing conversation summary:\n"
                f"{prev}\n\n"
                "New messages since last summary:\n"
                f"{new_text}\n\n"
                "Provide an updated summary that incorporates the new messages, "
                "preserving key facts, decisions, tool results, and unresolved topics."
            )
        else:
            prompt = (
                "Summarize the following conversation concisely, preserving key "
                "facts, decisions, and tool results:\n\n" + new_text
            )

        response = await self._llm.chat([Message(role="user", content=prompt)])
        return response.content

    async def _condense(self, summary: str) -> str:
        prompt = (
            "The following conversation summary is too long. Condense it to "
            "approximately half its length while preserving all key facts, "
            "decisions, and tool results:\n\n" + summary
        )
        try:
            response = await self._llm.chat([Message(role="user", content=prompt)])
            return response.content
        except Exception:
            logger.warning("Summary condensation failed; keeping long summary")
            return summary


def _partition_by_marker(
    messages: list[Message],
) -> tuple[list[Message], str, list[Message]]:
    system: list[Message] = [m for m in messages if m.role == "system"]
    non_system: list[Message] = [m for m in messages if m.role != "system"]

    prev_summary = ""
    non_summary: list[Message] = []
    for m in non_system:
        if m.text.startswith(_SUMMARY_MARKER):
            prev_summary = m.text[len(_SUMMARY_MARKER) :].strip()
        else:
            non_summary.append(m)

    for m in system:
        if m.text.startswith(_SUMMARY_MARKER):
            prev_summary = m.text[len(_SUMMARY_MARKER) :].strip()
            system.remove(m)
            break

    return system, prev_summary, non_summary


def _format_messages(messages: list[Message]) -> str:
    return "\n".join(f"[{m.role}]: {m.text}" for m in messages)


# ===================================================================
# Extract
# ===================================================================

class ExtractStrategy(CompressionStrategy):
    """Replace older messages with extracted key information.

    Uses :class:`KeyInfoExtractor` to pull entities, facts, preferences,
    and action items from the conversation.
    """

    def __init__(self, llm: ProviderAdapter, recent_keep: int = 4) -> None:
        self._llm = llm
        self._recent_keep = recent_keep

    async def compress(self, messages: list[Message], target_tokens: int) -> list[Message]:
        if len(messages) <= self._recent_keep + 1:
            return list(messages)

        from mindbot.context.extraction import KeyInfoExtractor

        system = [m for m in messages if m.role == "system"]
        non_system = [m for m in messages if m.role != "system"]

        to_extract = non_system[: -self._recent_keep]
        to_keep = non_system[-self._recent_keep:]

        extractor = KeyInfoExtractor(self._llm)
        key_info = await extractor.extract(to_extract)

        result = system + [key_info] + to_keep
        if _total_tokens(result) > target_tokens:
            return await TruncateStrategy().compress(messages, target_tokens)
        return result


# ===================================================================
# Mix (summarize + extract)
# ===================================================================

class MixStrategy(CompressionStrategy):
    """Hybrid: summarize older messages AND extract key information.

    Produces both a summary and a structured key-info message, then
    appends the most recent messages verbatim.
    """

    def __init__(
        self,
        llm: ProviderAdapter,
        recent_keep: int = 4,
        extract_threshold: int = 2,
    ) -> None:
        self._llm = llm
        self._recent_keep = recent_keep
        self._extract_threshold = extract_threshold

    async def compress(self, messages: list[Message], target_tokens: int) -> list[Message]:
        if len(messages) <= self._recent_keep + 1:
            return list(messages)

        from mindbot.context.extraction import KeyInfoExtractor

        system = [m for m in messages if m.role == "system"]
        non_system = [m for m in messages if m.role != "system"]

        to_compress = non_system[: -self._recent_keep]
        to_keep = non_system[-self._recent_keep:]

        if len(to_compress) <= self._extract_threshold:
            return system + to_keep

        # 1. Extract key info
        key_info = await KeyInfoExtractor(self._llm).extract(to_compress)

        # 2. Summarize
        text_block = "\n".join(f"[{m.role}]: {m.text}" for m in to_compress)
        summary_prompt = (
            "Summarize the following conversation concisely, preserving key "
            "facts, decisions, and tool results:\n\n" + text_block
        )
        try:
            response = await self._llm.chat(
                [Message(role="user", content=summary_prompt)]
            )
            summary_msg = Message(
                role="system",
                content=f"[Conversation summary] {response.content}",
            )
        except Exception:
            logger.warning("Mix summarize failed; using extract-only result")
            result = system + [key_info] + to_keep
            if _total_tokens(result) > target_tokens:
                return await TruncateStrategy().compress(messages, target_tokens)
            return result

        result = system + [summary_msg, key_info] + to_keep
        if _total_tokens(result) > target_tokens:
            return await TruncateStrategy().compress(messages, target_tokens)
        return result


# ===================================================================
# Archive
# ===================================================================

class ArchiveStrategy(CompressionStrategy):
    """Move older messages into the memory system, leaving a reference.

    Requires a :class:`MemoryManager` to persist the archived messages.
    """

    def __init__(
        self,
        memory: MemoryManager,
        recent_keep: int = 4,
    ) -> None:
        self._memory = memory
        self._recent_keep = recent_keep

    async def compress(self, messages: list[Message], target_tokens: int) -> list[Message]:
        if len(messages) <= self._recent_keep + 1:
            return list(messages)

        from mindbot.context.archiver import MemoryArchiver

        system = [m for m in messages if m.role == "system"]
        non_system = [m for m in messages if m.role != "system"]

        to_archive = non_system[: -self._recent_keep]
        to_keep = non_system[-self._recent_keep:]

        if not to_archive:
            return messages

        archiver = MemoryArchiver(self._memory)
        _archive_id, ref_msg = archiver.archive(to_archive)

        return system + [ref_msg] + to_keep


# ===================================================================
# Factory
# ===================================================================

def get_strategy(name: str, **kwargs: Any) -> CompressionStrategy:
    """Return a compression strategy by *name*.

    Supported names: ``truncate``, ``summarize``, ``rolling_summarize``,
    ``extract``, ``mix``, ``archive``.
    """
    recent_keep: int = kwargs.get("recent_keep", 4)

    if name == "truncate":
        return TruncateStrategy()

    if name == "summarize":
        llm = kwargs.get("llm")
        if llm is None:
            raise ValueError("SummarizeStrategy requires an 'llm' keyword argument")
        return SummarizeStrategy(llm, recent_keep=recent_keep)

    if name == "rolling_summarize":
        llm = kwargs.get("llm")
        if llm is None:
            raise ValueError("RollingSummarizeStrategy requires an 'llm' keyword argument")
        max_summary_tokens: int = kwargs.get("max_summary_tokens", 800)
        return RollingSummarizeStrategy(llm, recent_keep=recent_keep, max_summary_tokens=max_summary_tokens)

    if name == "extract":
        llm = kwargs.get("llm")
        if llm is None:
            raise ValueError("ExtractStrategy requires an 'llm' keyword argument")
        return ExtractStrategy(llm, recent_keep=recent_keep)

    if name == "mix":
        llm = kwargs.get("llm")
        if llm is None:
            raise ValueError("MixStrategy requires an 'llm' keyword argument")
        extract_threshold: int = kwargs.get("extract_threshold", 2)
        return MixStrategy(llm, recent_keep=recent_keep, extract_threshold=extract_threshold)

    if name == "archive":
        memory = kwargs.get("memory")
        if memory is None:
            raise ValueError("ArchiveStrategy requires a 'memory' keyword argument")
        return ArchiveStrategy(memory, recent_keep=recent_keep)

    raise ValueError(f"Unknown compression strategy: {name!r}")


# ===================================================================
# Helpers
# ===================================================================

def _truncate_messages_sync(messages: list[Message], target_tokens: int) -> list[Message]:
    """Synchronous truncation – pure CPU, no I/O.

    Used by :class:`TruncateStrategy` and by the packer's sync compress
    callbacks.
    """
    system: list[Message] = [m for m in messages if m.role == "system"]
    others: list[Message] = [m for m in messages if m.role != "system"]

    system_tokens = sum(estimate_tokens(m.text) for m in system)
    if system_tokens > target_tokens:
        return system

    sorted_by_priority = sorted(
        enumerate(others), key=lambda pair: _drop_priority(pair[1])
    )
    dropped: set[int] = set()
    current = system_tokens + sum(estimate_tokens(m.text) for m in others)
    for idx, msg in sorted_by_priority:
        if current <= target_tokens:
            break
        if _drop_priority(msg) >= 10:
            break
        dropped.add(idx)
        current -= estimate_tokens(msg.text)

    remaining = [m for i, m in enumerate(others) if i not in dropped]

    while remaining and current > target_tokens:
        removed = remaining.pop(0)
        current -= estimate_tokens(removed.text)

    return system + remaining


def _total_tokens(messages: list[Message]) -> int:
    return sum(estimate_tokens(m.text) for m in messages)


