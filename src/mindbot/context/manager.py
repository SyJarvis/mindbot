"""Context manager – block-based context window with per-block token budgets."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

from mindbot.config.schema import ContextBlocksConfig, ContextConfig
from mindbot.context.checkpoint import Checkpoint
from mindbot.context.compression import CompressionStrategy, TruncateStrategy
from mindbot.context.models import Message, MessageRole
from mindbot.utils import estimate_tokens, get_logger

logger = get_logger("context.manager")

# Default ratios when explicit block budgets are not configured.
_DEFAULT_RATIOS: dict[str, float] = {
    "system_identity": 0.15,
    "memory": 0.20,
    "conversation": 0.50,
    "user_input": 0.15,
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
    tool coordination, etc.).  That responsibility belongs to the
    :class:`~mindbot.agent.scheduler.Scheduler` at Layer 2.

    Blocks (in message-assembly order):

    * **system_identity** – system prompt / persona.
    * **memory** – retrieved memory chunks (populated by Scheduler each turn).
    * **conversation** – multi-turn dialogue history; subject to compression.
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
    ) -> None:
        if config is not None:
            self._config = config
        else:
            self._config = ContextConfig(max_tokens=max_tokens)

        self.max_tokens = self._config.max_tokens

        if strategy is not None:
            self._strategy: CompressionStrategy = strategy
        elif self._config.compression == "truncate":
            self._strategy = TruncateStrategy()
        else:
            from mindbot.context.compression import get_strategy
            self._strategy = get_strategy(
                self._config.compression,
                recent_keep=self._config.compression_config.recent_keep,
                extract_threshold=self._config.compression_config.extract_threshold,
            )

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
        block = self._blocks["system_identity"]
        msg = Message(role="system", content=content)
        msg.token_count = estimate_tokens(msg.text)
        block.messages = [msg]

    # ------------------------------------------------------------------
    # Memory block (populated externally each turn)
    # ------------------------------------------------------------------

    def set_memory_messages(self, messages: list[Message]) -> None:
        """Replace the memory block contents (called by Scheduler)."""
        block = self._blocks["memory"]
        kept: list[Message] = []
        total = 0
        for msg in messages:
            self._ensure_token_count(msg)
            if total + msg.token_count > block.max_tokens:
                break
            kept.append(msg)
            total += msg.token_count
        block.messages = kept

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
    # User input block (current turn only)
    # ------------------------------------------------------------------

    def set_user_input(self, message: Message) -> None:
        """Set the current-turn user input (single message)."""
        self._ensure_token_count(message)
        self._blocks["user_input"].messages = [message]

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
        conv = self._blocks["conversation"]
        if conv.token_count > conv.max_tokens:
            logger.info(
                "Conversation block budget exceeded (%d > %d) – compacting",
                conv.token_count,
                conv.max_tokens,
            )
            self.compact()

    def compact(self) -> None:
        """Compress the conversation block using the configured strategy."""
        conv = self._blocks["conversation"]
        conv.messages = self._strategy.compress(conv.messages, conv.max_tokens)
        for m in conv.messages:
            m.token_count = estimate_tokens(m.text)

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
        """Prepare message list for LLM call with proactive compression.

        This method should be called before sending messages to the LLM.
        It proactively checks and compresses the context to avoid
        exceeding token limits.

        Returns:
            List of messages ready for LLM consumption
        """
        # Proactively check and compress if needed
        self._check_and_compact()

        # Return messages in assembly order
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
