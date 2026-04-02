"""Context compression strategies.

Strategies operate on the **conversation** block only.  The caller
(``ContextManager.compact``) passes in the conversation messages and the
block's token budget as ``target_tokens``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from src.mindbot.context.models import Message
from src.mindbot.utils import estimate_tokens, get_logger, run_sync

if TYPE_CHECKING:
    from src.mindbot.memory.manager import MemoryManager
    from src.mindbot.providers.adapter import ProviderAdapter

logger = get_logger("context.compression")


# ===================================================================
# Base
# ===================================================================

class CompressionStrategy(ABC):
    """Base class for context compression strategies."""

    @abstractmethod
    def compress(self, messages: list[Message], target_tokens: int) -> list[Message]:
        """Return a compressed copy of *messages* that fits within *target_tokens*."""


# ===================================================================
# Truncate
# ===================================================================

class TruncateStrategy(CompressionStrategy):
    """Drop the oldest non-system messages until the budget is met.

    System messages are always retained.
    """

    def compress(self, messages: list[Message], target_tokens: int) -> list[Message]:
        system: list[Message] = [m for m in messages if m.role == "system"]
        others: list[Message] = [m for m in messages if m.role != "system"]

        total = sum(estimate_tokens(m.text) for m in system)
        keep: list[Message] = []

        for msg in reversed(others):
            cost = estimate_tokens(msg.text)
            if total + cost > target_tokens:
                break
            keep.append(msg)
            total += cost

        keep.reverse()
        return system + keep


# ===================================================================
# Summarize
# ===================================================================

class SummarizeStrategy(CompressionStrategy):
    """Summarize older messages via the LLM, keeping recent ones verbatim."""

    def __init__(self, llm: ProviderAdapter, recent_keep: int = 4) -> None:
        self._llm = llm
        self._recent_keep = recent_keep

    def compress(self, messages: list[Message], target_tokens: int) -> list[Message]:
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
            response = run_sync(
                self._llm.chat([Message(role="user", content=summary_prompt)])
            )
            summary_msg = Message(
                role="system",
                content=f"[Conversation summary] {response.content}",
            )
        except Exception:
            logger.warning("Summarize failed; falling back to truncation")
            return TruncateStrategy().compress(messages, target_tokens)

        return system + [summary_msg] + to_keep


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

    def compress(self, messages: list[Message], target_tokens: int) -> list[Message]:
        if len(messages) <= self._recent_keep + 1:
            return list(messages)

        from src.mindbot.context.extraction import KeyInfoExtractor

        system = [m for m in messages if m.role == "system"]
        non_system = [m for m in messages if m.role != "system"]

        to_extract = non_system[: -self._recent_keep]
        to_keep = non_system[-self._recent_keep:]

        extractor = KeyInfoExtractor(self._llm)
        key_info = extractor.extract(to_extract)

        result = system + [key_info] + to_keep
        if _total_tokens(result) > target_tokens:
            return TruncateStrategy().compress(messages, target_tokens)
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

    def compress(self, messages: list[Message], target_tokens: int) -> list[Message]:
        if len(messages) <= self._recent_keep + 1:
            return list(messages)

        from src.mindbot.context.extraction import KeyInfoExtractor

        system = [m for m in messages if m.role == "system"]
        non_system = [m for m in messages if m.role != "system"]

        to_compress = non_system[: -self._recent_keep]
        to_keep = non_system[-self._recent_keep:]

        if len(to_compress) <= self._extract_threshold:
            return system + to_keep

        # 1. Extract key info
        key_info = KeyInfoExtractor(self._llm).extract(to_compress)

        # 2. Summarize
        text_block = "\n".join(f"[{m.role}]: {m.text}" for m in to_compress)
        summary_prompt = (
            "Summarize the following conversation concisely, preserving key "
            "facts, decisions, and tool results:\n\n" + text_block
        )
        try:
            response = run_sync(
                self._llm.chat([Message(role="user", content=summary_prompt)])
            )
            summary_msg = Message(
                role="system",
                content=f"[Conversation summary] {response.content}",
            )
        except Exception:
            logger.warning("Mix summarize failed; using extract-only result")
            result = system + [key_info] + to_keep
            if _total_tokens(result) > target_tokens:
                return TruncateStrategy().compress(messages, target_tokens)
            return result

        result = system + [summary_msg, key_info] + to_keep
        if _total_tokens(result) > target_tokens:
            return TruncateStrategy().compress(messages, target_tokens)
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

    def compress(self, messages: list[Message], target_tokens: int) -> list[Message]:
        if len(messages) <= self._recent_keep + 1:
            return list(messages)

        from src.mindbot.context.archiver import MemoryArchiver

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

    Supported names: ``truncate``, ``summarize``, ``extract``, ``mix``,
    ``archive``.
    """
    recent_keep: int = kwargs.get("recent_keep", 4)

    if name == "truncate":
        return TruncateStrategy()

    if name == "summarize":
        llm = kwargs.get("llm")
        if llm is None:
            raise ValueError("SummarizeStrategy requires an 'llm' keyword argument")
        return SummarizeStrategy(llm, recent_keep=recent_keep)

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

def _total_tokens(messages: list[Message]) -> int:
    return sum(estimate_tokens(m.text) for m in messages)
