"""Context manager – block-based context state container.

The manager stores per-block messages exactly as they were written.  It
no longer enforces per-block token budgets at write time: that decision
has moved to :class:`~mindbot.context.packer.ContextPacker`, which
packs candidate items into the actual prompt for each turn.

What this class *does* still own:

* The canonical block layout and ordering.
* Soft per-block budgets (``ContextBlock.max_tokens``) used as hints by
  the packer and surfaced for observability.
* A safety-net compaction on the conversation block that fires when the
  buffered history would exceed the *total* context budget, so the
  in-memory session state stays bounded across long sessions.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from mindbot.config.schema import ContextConfig
from mindbot.context.checkpoint import Checkpoint
from mindbot.context.compression import CompressionStrategy, TruncateStrategy, get_strategy
from mindbot.context.models import Message, MessageRole
from mindbot.utils import estimate_tokens
from mindbot.logging import logger


# Default ratios when explicit block budgets are not configured.
_DEFAULT_RATIOS: dict[str, float] = {
    "system_identity": 0.12,
    "skills_overview": 0.08,
    "skills_detail": 0.15,
    "memory": 0.15,
    "conversation": 0.35,
    "intent_state": 0.05,
    "user_input": 0.10,
}


@dataclass
class ContextBlock:
    """A named partition of the context window."""

    name: str
    max_tokens: int
    messages: list[Message] = field(default_factory=list)

    @property
    def token_count(self) -> int:
        return sum(m.token_count for m in self.messages)

    @property
    def remaining(self) -> int:
        return max(0, self.max_tokens - self.token_count)


def _resolve_block_budgets(
    config: ContextConfig,
) -> dict[str, int]:
    """Compute per-block token budgets from config, falling back to ratios."""
    total = config.max_tokens
    blocks_cfg = config.blocks
    budgets: dict[str, int] = {}
    for name, default_ratio in _DEFAULT_RATIOS.items():
        explicit = getattr(blocks_cfg, name, None)
        if explicit is not None:
            budgets[name] = explicit
        else:
            budgets[name] = int(total * default_ratio)
    return budgets


class ContextManager:
    """L3 Conversation Domain – manages context state and compression.

    This class is a **pure state + compression** component at Layer 3 of the
    architecture.  It owns the block-based context window and token budgets
    but does **not** perform cross-subsystem orchestration (memory retrieval,
    tool coordination, etc.).  Assembly of the final LLM prompt is the
    responsibility of :class:`~mindbot.agent.input_builder.InputBuilder`.

    Blocks (in canonical order):

    * **system_identity** – system prompt / persona.
    * **skills_overview** – always-visible skill summaries.
    * **skills_detail** – selected skill bodies for the current turn.
    * **memory** – retrieved memory chunks (populated per turn).
    * **conversation** – multi-turn dialogue history; subject to compression.
    * **intent_state** – optional turn-scoped intent/context hints.
    * **user_input** – the current user message.

    When the conversation block exceeds its budget the configured compression
    strategy is applied automatically.
    """

    def __init__(
        self,
        config: ContextConfig | None = None,
        *,
        max_tokens: int = 8000,
        strategy: CompressionStrategy | None = None,
        llm: Any | None = None,
    ) -> None:
        if config is not None:
            self._config = config
        else:
            self._config = ContextConfig(max_tokens=max_tokens)

        self.max_tokens = self._config.max_tokens

        if strategy is not None:
            self._strategy: CompressionStrategy = strategy
        else:
            try:
                self._strategy = get_strategy(
                    self._config.compression,
                    llm=llm,
                    recent_keep=self._config.compression_config.recent_keep,
                    extract_threshold=self._config.compression_config.extract_threshold,
                    max_summary_tokens=self._config.compression_config.max_summary_tokens,
                )
            except (ValueError, TypeError):
                logger.warning(
                    "Cannot create strategy %r (missing dependencies); "
                    "falling back to truncate",
                    self._config.compression,
                )
                self._strategy = TruncateStrategy()

        self._needs_compaction: bool = False
        self._checkpoints: dict[str, Checkpoint] = {}

        budgets = _resolve_block_budgets(self._config)
        self._blocks: dict[str, ContextBlock] = {
            name: ContextBlock(name=name, max_tokens=budget)
            for name, budget in budgets.items()
        }

    # ------------------------------------------------------------------
    # Block accessors
    # ------------------------------------------------------------------

    def get_block(self, name: str) -> ContextBlock:
        return self._blocks[name]

    @property
    def block_names(self) -> list[str]:
        return list(_DEFAULT_RATIOS.keys())

    # ------------------------------------------------------------------
    # Convenience: flat message list (backward-compatible)
    # ------------------------------------------------------------------

    @property
    def messages(self) -> list[Message]:
        """All messages across blocks, in assembly order."""
        result: list[Message] = []
        for name in self.block_names:
            result.extend(self._blocks[name].messages)
        return result

    @messages.setter
    def messages(self, value: list[Message]) -> None:
        """Bulk-replace: put everything into the conversation block.

        This setter exists for backward compatibility with code that
        directly assigns ``context.messages = ...``.
        """
        self.clear()
        for msg in value:
            if msg.role == "system":
                self._ensure_token_count(msg)
                self._blocks["system_identity"].messages.append(msg)
            else:
                self._ensure_token_count(msg)
                self._blocks["conversation"].messages.append(msg)
        self._check_and_compact()

    @property
    def total_tokens(self) -> int:
        return sum(b.token_count for b in self._blocks.values())

    # ------------------------------------------------------------------
    # System identity
    # ------------------------------------------------------------------

    def set_system_identity(self, content: str) -> None:
        """Set (replace) the system identity message."""
        msg = Message(role="system", content=content)
        msg.token_count = estimate_tokens(msg.text)
        self._set_single_message_block("system_identity", msg)

    # ------------------------------------------------------------------
    # Skills blocks (current turn only)
    # ------------------------------------------------------------------

    def set_skills_overview(self, content: str | Message | None) -> None:
        """Set an optional overview block listing visible skills."""
        if content is None:
            self.clear_skills_overview()
            return

        if isinstance(content, Message):
            msg = content
        else:
            msg = Message(role="system", content=content)
            msg.token_count = estimate_tokens(msg.text)
        self._ensure_token_count(msg)
        self._set_single_message_block("skills_overview", msg)

    def clear_skills_overview(self) -> None:
        self._blocks["skills_overview"].messages.clear()

    def set_skills_detail(self, content: str | Message | None) -> None:
        """Set an optional detail block for selected skill instructions."""
        if content is None:
            self.clear_skills_detail()
            return

        if isinstance(content, Message):
            msg = content
        else:
            msg = Message(role="system", content=content)
            msg.token_count = estimate_tokens(msg.text)
        self._ensure_token_count(msg)
        self._set_single_message_block("skills_detail", msg)

    def clear_skills_detail(self) -> None:
        self._blocks["skills_detail"].messages.clear()

    # ------------------------------------------------------------------
    # Memory block (populated externally each turn)
    # ------------------------------------------------------------------

    def set_memory_messages(self, messages: list[Message]) -> None:
        """Replace the memory block contents (called by Scheduler).

        All messages are stored verbatim.  The packer is responsible
        for fitting memory into the per-turn token budget; truncating
        at the manager level would prevent the packer from keeping a
        compressed subset later.
        """
        for msg in messages:
            self._ensure_token_count(msg)
        self._blocks["memory"].messages = list(messages)

    # ------------------------------------------------------------------
    # Conversation block
    # ------------------------------------------------------------------

    def add_conversation_message(
        self,
        role: MessageRole,
        content: str,
        **kwargs: Any,
    ) -> Message:
        """Create and append a message to the conversation block."""
        msg = Message(role=role, content=content, **kwargs)
        msg.token_count = estimate_tokens(msg.text)
        self._blocks["conversation"].messages.append(msg)
        self._check_and_compact()
        return msg

    def add_conversation(self, message: Message) -> None:
        """Append an existing message to the conversation block."""
        self._ensure_token_count(message)
        self._blocks["conversation"].messages.append(message)
        self._check_and_compact()

    # ------------------------------------------------------------------
    # Intent block (current turn only)
    # ------------------------------------------------------------------

    def set_intent_state(self, content: str | Message | None) -> None:
        """Set an optional intent-state hint for the current turn."""
        if content is None:
            self.clear_intent_state()
            return

        if isinstance(content, Message):
            msg = content
        else:
            msg = Message(role="system", content=content)
            msg.token_count = estimate_tokens(msg.text)
        self._ensure_token_count(msg)
        self._set_single_message_block("intent_state", msg)

    def clear_intent_state(self) -> None:
        self._blocks["intent_state"].messages.clear()

    # ------------------------------------------------------------------
    # User input block (current turn only)
    # ------------------------------------------------------------------

    def set_user_input(self, message: Message) -> None:
        """Set the current-turn user input (single message)."""
        self._ensure_token_count(message)
        self._set_single_message_block("user_input", message)

    def clear_user_input(self) -> None:
        self._blocks["user_input"].messages.clear()

    # ------------------------------------------------------------------
    # Legacy helpers (backward-compatible with old flat API)
    # ------------------------------------------------------------------

    def add_message(
        self,
        role: MessageRole,
        content: str,
        **kwargs: Any,
    ) -> Message:
        """Create and append a :class:`Message` (backward-compatible)."""
        msg = Message(role=role, content=content, **kwargs)
        msg.token_count = estimate_tokens(msg.text)
        if role == "system":
            self._blocks["system_identity"].messages.append(msg)
        else:
            self._blocks["conversation"].messages.append(msg)
            self._check_and_compact()
        return msg

    def add(self, message: Message) -> None:
        """Append an existing message (backward-compatible)."""
        self._ensure_token_count(message)
        if message.role == "system":
            self._blocks["system_identity"].messages.append(message)
        else:
            self._blocks["conversation"].messages.append(message)
            self._check_and_compact()

    # ------------------------------------------------------------------
    # Compaction (conversation block only)
    # ------------------------------------------------------------------

    def _check_and_compact(self) -> None:
        """Check whether the conversation block needs compaction.

        Sets an internal flag so that actual (potentially async) compression
        is deferred to :meth:`maybe_compact`, which should be called before
        the next LLM turn.
        """
        conv = self._blocks["conversation"]
        trigger = self.max_tokens * self._config.compression_config.compact_trigger_ratio
        if conv.token_count > trigger:
            logger.info(
                "Conversation buffer exceeded trigger line (%d > %.0f) – scheduled for compaction",
                conv.token_count,
                trigger,
            )
            self._needs_compaction = True

    async def maybe_compact(self) -> int | None:
        """Run pending compaction if the flag was set.

        Called by the async build path (:class:`~mindbot.agent.input_builder.InputBuilder`)
        before assembling the next LLM prompt.

        Returns:
            Token count after compaction, or ``None`` if no compaction was needed.
        """
        if not self._needs_compaction:
            return None
        self._needs_compaction = False
        return await self.compact()

    async def compact(self) -> int:
        """Compress the conversation block to the target ratio.

        Uses the configured compression strategy (e.g. ``SummarizeStrategy``),
        falling back to :class:`TruncateStrategy` on failure.

        Returns:
            Token count of the conversation block after compaction.
        """
        conv = self._blocks["conversation"]
        before = conv.token_count
        target = int(self.max_tokens * self._config.compression_config.compact_target_ratio)
        try:
            conv.messages = await self._strategy.compress(conv.messages, target)
        except Exception:
            logger.warning("Strategy %r failed; falling back to truncate", type(self._strategy).__name__)
            conv.messages = await TruncateStrategy().compress(conv.messages, target)
        for m in conv.messages:
            m.token_count = estimate_tokens(m.text)
        after = conv.token_count
        logger.info("Compacted conversation: %d → %d tokens", before, after)
        return after

    # ------------------------------------------------------------------
    # Assembly (ordered block output)
    # ------------------------------------------------------------------

    def get_messages(self, last_n: int | None = None) -> list[Message]:
        """Return all messages in assembly order, optionally the last *n*."""
        all_msgs = self.messages
        if last_n is not None:
            return all_msgs[-last_n:]
        return all_msgs

    def get_block_messages(self, block_name: str) -> list[Message]:
        """Return messages from a single block."""
        return list(self._blocks[block_name].messages)

    # ------------------------------------------------------------------
    # LLM preparation (proactive compression)
    # ------------------------------------------------------------------

    def prepare_for_llm(self) -> list[Message]:
        """Utility: return messages in canonical order.

        .. note::

            The main chain uses :class:`~mindbot.agent.input_builder.InputBuilder`
            to assemble the final prompt, which calls :meth:`maybe_compact`
            asynchronously before packing.  This method does **not** trigger
            compaction — it only returns the current state.

        Returns:
            List of messages in assembly order.
        """
        return self.messages

    # ------------------------------------------------------------------
    # Checkpoints
    # ------------------------------------------------------------------

    def create_checkpoint(self, name: str = "") -> str:
        """Snapshot all blocks; return the checkpoint id."""
        cid = uuid.uuid4().hex
        snapshot: dict[str, list[Message]] = {
            bname: list(block.messages)
            for bname, block in self._blocks.items()
        }
        self._checkpoints[cid] = Checkpoint(
            id=cid,
            name=name,
            messages=self.messages,
        )
        self._checkpoints[cid]._block_snapshot = snapshot  # type: ignore[attr-defined]
        return cid

    def rollback_to_checkpoint(self, checkpoint_id: str) -> None:
        """Restore block contents from a checkpoint."""
        cp = self._checkpoints.get(checkpoint_id)
        if cp is None:
            raise KeyError(f"Checkpoint {checkpoint_id!r} not found")
        snapshot: dict[str, list[Message]] = getattr(cp, "_block_snapshot", {})
        if snapshot:
            for bname, msgs in snapshot.items():
                if bname in self._blocks:
                    self._blocks[bname].messages = list(msgs)
        else:
            self.messages = list(cp.messages)

    def list_checkpoints(self) -> list[Checkpoint]:
        return list(self._checkpoints.values())

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Remove all messages from every block (but keep checkpoints)."""
        for block in self._blocks.values():
            block.messages.clear()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_token_count(msg: Message) -> None:
        if msg.token_count == 0:
            msg.token_count = estimate_tokens(msg.text)

    def _set_single_message_block(self, block_name: str, message: Message) -> None:
        """Replace a single-message block.

        Stores the message verbatim.  Per-block token budgets are now
        honoured by :class:`~mindbot.context.packer.ContextPacker` at
        prompt-assembly time, not by the state container.
        """
        self._ensure_token_count(message)
        self._blocks[block_name].messages = [message]
