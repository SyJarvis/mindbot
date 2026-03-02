"""Scheduler – lightweight coordinator that assembles per-turn LLM messages.

Lives at the **L2 Application / Orchestration** layer.  The Scheduler reads
from ContextManager (L3 – blocks), MemoryManager (L4 – retrieval), and
ToolRegistry (L4 – tool definitions) to produce the final ``list[Message]``
sent to the LLM each turn.  After the LLM responds, it commits new messages
back into the conversation block of the ContextManager.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Literal

from mindbot.context.manager import ContextManager
from mindbot.context.models import Message, MessageContent
from mindbot.utils import estimate_tokens, get_logger

ToolPersistence = Literal["none", "summary", "full"]

if TYPE_CHECKING:
    from mindbot.memory.manager import MemoryManager
    from mindbot.memory.types import MemoryChunk
    from mindbot.capability.backends.tooling.models import Tool
    from mindbot.capability.backends.tooling.registry import ToolRegistry

logger = get_logger("agent.scheduler")


class Scheduler:
    """Assembles per-turn messages from Context, Memory, and Tools.

    Lifecycle per turn::

        messages = scheduler.assemble(user_input_text)
        response = await llm.chat(messages)
        scheduler.commit(user_msg, assistant_msg)

    The Scheduler never owns LLM / Memory / Tools state — it only reads
    and coordinates.
    """

    def __init__(
        self,
        context: ContextManager,
        memory: MemoryManager | None = None,
        tool_registry: ToolRegistry | None = None,
        *,
        memory_top_k: int = 5,
        system_prompt: str = "",
        tool_persistence: ToolPersistence = "none",
    ) -> None:
        self._ctx = context
        self._memory = memory
        self._tool_registry = tool_registry
        self._memory_top_k = memory_top_k
        self._tool_persistence: ToolPersistence = tool_persistence
        if system_prompt:
            self._ctx.set_system_identity(system_prompt)

    # ------------------------------------------------------------------
    # Assembly
    # ------------------------------------------------------------------

    def assemble(
        self,
        user_input: str | MessageContent,
        *,
        session_id: str | None = None,
    ) -> list[Message]:
        """Build the full message list for one LLM call.

        Steps:
        1. Retrieve relevant memories and populate the memory block.
        2. Set the current user input in the user_input block.
        3. Concatenate blocks in order: system_identity -> memory ->
           conversation -> user_input.

        Tool definitions are **not** injected here — they are passed via
        ``ProviderAdapter.bind_tools()`` at the LLM call site.

        Returns the assembled ``list[Message]`` ready for the LLM.
        """
        t0 = time.perf_counter()

        query_text = user_input if isinstance(user_input, str) else _extract_text(user_input)
        self._populate_memory_block(query_text)

        user_msg = Message(role="user", content=user_input)
        user_msg.token_count = estimate_tokens(user_msg.text)
        self._ctx.set_user_input(user_msg)

        assembled: list[Message] = []
        for block_name in self._ctx.block_names:
            assembled.extend(self._ctx.get_block_messages(block_name))

        mem_block = self._ctx.get_block("memory")
        conv_block = self._ctx.get_block("conversation")
        elapsed_ms = (time.perf_counter() - t0) * 1000

        logger.info(
            "scheduler.assemble: messages=%d mem_hits=%d "
            "conv_tokens=%d/%d total_tokens=%d elapsed_ms=%.1f",
            len(assembled),
            len(mem_block.messages),
            conv_block.token_count,
            conv_block.max_tokens,
            self._ctx.total_tokens,
            elapsed_ms,
        )
        return assembled

    # ------------------------------------------------------------------
    # Commit (post-LLM)
    # ------------------------------------------------------------------

    def commit(
        self,
        user_text: str,
        assistant_text: str,
        *,
        extra_messages: list[Message] | None = None,
    ) -> None:
        """Persist this turn's messages into the conversation block.

        Call this **after** the LLM has responded.  The user and assistant
        messages are appended to the conversation block.  Any additional
        messages (e.g. tool calls/results from an agent loop) can be passed
        via *extra_messages* and are persisted according to the configured
        ``tool_persistence`` strategy (none / summary / full).

        The user_input block is cleared after commit since the message has
        been incorporated into conversation history.
        """
        t0 = time.perf_counter()

        self._ctx.add_conversation_message("user", user_text)

        if extra_messages:
            self._persist_tool_messages(extra_messages)

        self._ctx.add_conversation_message("assistant", assistant_text)
        self._ctx.clear_user_input()

        conv_block = self._ctx.get_block("conversation")
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info(
            "scheduler.commit: conv_tokens=%d/%d total_tokens=%d "
            "tool_msgs=%d persistence=%s elapsed_ms=%.1f",
            conv_block.token_count,
            conv_block.max_tokens,
            self._ctx.total_tokens,
            len(extra_messages) if extra_messages else 0,
            self._tool_persistence,
            elapsed_ms,
        )

    def commit_messages(self, messages: list[Message]) -> None:
        """Bulk-commit a list of messages into the conversation block.

        Useful after an agent loop where the full message trail
        (user -> assistant -> tool -> assistant ...) is already available.
        """
        for msg in messages:
            if msg.role == "system":
                continue
            self._ctx.add_conversation(msg)
        self._ctx.clear_user_input()

    # ------------------------------------------------------------------
    # Tool message persistence
    # ------------------------------------------------------------------

    def _persist_tool_messages(self, messages: list[Message]) -> None:
        """Persist tool-related messages according to the configured strategy."""
        if self._tool_persistence == "none":
            return

        if self._tool_persistence == "full":
            for msg in messages:
                if msg.role == "system":
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
    # Memory block population
    # ------------------------------------------------------------------

    def _populate_memory_block(self, query: str) -> None:
        """Retrieve memories and fill the memory block."""
        if self._memory is None:
            self._ctx.set_memory_messages([])
            return

        chunks: list[MemoryChunk] = []
        try:
            chunks = self._memory.search(query, top_k=self._memory_top_k)
        except Exception:
            logger.debug("Memory search failed; continuing without memories")

        if not chunks:
            self._ctx.set_memory_messages([])
            return

        ctx_text = "\n".join(f"- {c.text}" for c in chunks)
        memory_msg = Message(
            role="system",
            content=f"Relevant context from memory:\n{ctx_text}",
        )
        memory_msg.token_count = estimate_tokens(memory_msg.text)
        self._ctx.set_memory_messages([memory_msg])

    # ------------------------------------------------------------------
    # Tool helpers
    # ------------------------------------------------------------------

    def get_tools(self) -> list[Tool]:
        """Return tools from the registry (for ``bind_tools``)."""
        if self._tool_registry is None:
            return []
        return self._tool_registry.list_tools()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def save_to_memory(self, user_text: str, assistant_text: str) -> None:
        """Write this turn to short-term memory (fire-and-forget)."""
        if self._memory is None:
            return
        try:
            self._memory.append_to_short_term(f"User: {user_text}")
            self._memory.append_to_short_term(f"Assistant: {assistant_text}")
        except Exception:
            logger.debug("Failed to persist turn to memory")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_text(content: MessageContent) -> str:
    """Get plain text from a MessageContent value."""
    if isinstance(content, str):
        return content
    from mindbot.context.models import TextPart
    parts = [p.text for p in content if isinstance(p, TextPart)]
    return "".join(parts)
