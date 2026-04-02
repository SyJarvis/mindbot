"""Phase B input builder – assembles per-turn LLM messages.

The ``InputBuilder`` reads from :class:`~mindbot.context.manager.ContextManager`
(blocks) and :class:`~mindbot.memory.manager.MemoryManager` (retrieval) to
produce the final ``list[Message]`` sent to the LLM each turn.

Tool definitions are **not** injected here — they are passed via
``ProviderAdapter.bind_tools()`` at the LLM call site.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from src.mindbot.context.manager import ContextManager
from src.mindbot.context.models import Message, MessageContent
from src.mindbot.utils import estimate_tokens, get_logger

if TYPE_CHECKING:
    from src.mindbot.memory.manager import MemoryManager
    from src.mindbot.memory.types import MemoryChunk

logger = get_logger("agent.input_builder")


def _extract_text(content: MessageContent) -> str:
    """Get plain text from a MessageContent value."""
    if isinstance(content, str):
        return content
    from src.mindbot.context.models import TextPart

    parts = [p.text for p in content if isinstance(p, TextPart)]
    return "".join(parts)


class InputBuilder:
    """Assembles per-turn LLM input from Context and Memory.

    Lifecycle per turn::

        messages = builder.build(user_input_text)
        # pass messages to TurnEngine.run()

    The InputBuilder never owns LLM / Memory state — it only reads blocks
    from the :class:`~mindbot.context.manager.ContextManager` and populates
    the memory block via the :class:`~mindbot.memory.manager.MemoryManager`.
    """

    def __init__(
        self,
        context: ContextManager,
        memory: "MemoryManager | None" = None,
        *,
        memory_top_k: int = 5,
        system_prompt: str = "",
    ) -> None:
        self._ctx = context
        self._memory = memory
        self._memory_top_k = memory_top_k
        if system_prompt:
            self._ctx.set_system_identity(system_prompt)

    @property
    def context(self) -> ContextManager:
        """The underlying context manager (shared state)."""
        return self._ctx

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(
        self,
        user_input: str | MessageContent,
        *,
        session_id: str | None = None,
        intent_state: str | None = None,
    ) -> list[Message]:
        """Build the full message list for one LLM call.

        Steps:
        1. Retrieve relevant memories and populate the memory block.
        2. Populate the optional intent_state block.
        3. Set the current user input in the user_input block.
        4. Concatenate blocks in canonical order: system_identity → memory →
           conversation → intent_state → user_input.

        Returns the assembled ``list[Message]`` ready for the LLM.
        """
        t0 = time.perf_counter()

        query_text = (
            user_input if isinstance(user_input, str) else _extract_text(user_input)
        )
        self._populate_memory_block(query_text)
        self._ctx.set_intent_state(intent_state)

        user_msg = Message(role="user", content=user_input)
        user_msg.token_count = estimate_tokens(user_msg.text)
        self._ctx.set_user_input(user_msg)

        # Read blocks directly in canonical order
        assembled: list[Message] = []
        for block_name in self._ctx.block_names:
            assembled.extend(self._ctx.get_block_messages(block_name))

        mem_block = self._ctx.get_block("memory")
        conv_block = self._ctx.get_block("conversation")
        elapsed_ms = (time.perf_counter() - t0) * 1000

        logger.info(
            "input_builder.build: messages=%d mem_hits=%d "
            "conv_tokens=%d/%d total_tokens=%d elapsed_ms=%.1f",
            len(assembled),
            len(mem_block.messages),
            conv_block.token_count,
            conv_block.max_tokens,
            self._ctx.total_tokens,
            elapsed_ms,
        )
        return assembled

    build_messages = build

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
