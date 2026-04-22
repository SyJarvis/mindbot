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

from mindbot.context.manager import ContextManager
from mindbot.context.models import Message, MessageContent
from mindbot.utils import estimate_tokens, get_logger

if TYPE_CHECKING:
    from mindbot.config.schema import SkillsConfig
    from mindbot.memory.manager import MemoryManager
    from mindbot.memory.types import MemoryShard
    from mindbot.skills.registry import SkillRegistry

from mindbot.skills.render import render_skills_detail, render_skills_overview
from mindbot.skills.selector import SkillSelector

logger = get_logger("agent.input_builder")


def _extract_text(content: MessageContent) -> str:
    """Get plain text from a MessageContent value."""
    if isinstance(content, str):
        return content
    from mindbot.context.models import TextPart

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
        skill_registry: "SkillRegistry | None" = None,
        skills_config: "SkillsConfig | None" = None,
    ) -> None:
        self._ctx = context
        self._memory = memory
        self._memory_top_k = memory_top_k
        self._skill_registry = skill_registry
        self._skills_config = skills_config
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
        1. Select and populate skills overview/detail blocks.
        2. Retrieve relevant memories and populate the memory block.
        3. Populate the optional intent_state block.
        4. Set the current user input in the user_input block.
        5. Concatenate blocks in canonical order.

        Returns the assembled ``list[Message]`` ready for the LLM.
        """
        t0 = time.perf_counter()

        query_text = (
            user_input if isinstance(user_input, str) else _extract_text(user_input)
        )
        self._populate_skills_blocks(query_text)
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
    # Skills block population
    # ------------------------------------------------------------------

    def _populate_skills_blocks(self, query: str) -> None:
        """Populate the skills overview/detail blocks for the current turn."""
        if self._skills_config is None:
            self._ctx.clear_skills_overview()
            self._ctx.clear_skills_detail()
            return

        selector = SkillSelector(
            self._skill_registry,
            enabled=self._skills_config.enabled,
            always_include=self._skills_config.always_include,
            max_visible=self._skills_config.max_visible,
            max_detail_load=self._skills_config.max_detail_load,
            trigger_mode=self._skills_config.trigger_mode,
        )
        result = selector.select(query)

        overview = render_skills_overview(result.summaries)
        detail = render_skills_detail(result.selections, self._skill_registry)

        self._ctx.set_skills_overview(overview or None)
        self._ctx.set_skills_detail(detail or None)

    # ------------------------------------------------------------------
    # Memory block population
    # ------------------------------------------------------------------

    def _populate_memory_block(self, query: str) -> None:
        """Retrieve memories and fill the memory block."""
        if self._memory is None:
            self._ctx.set_memory_messages([])
            return

        shards: list[MemoryShard] = []
        try:
            shards = self._memory.search(query, top_k=self._memory_top_k)
        except Exception:
            logger.debug("Memory search failed; continuing without memories")

        if not shards:
            self._ctx.set_memory_messages([])
            return

        ctx_text = "\n".join(f"- {s.text}" for s in shards)
        memory_msg = Message(
            role="system",
            content=f"Relevant context from memory:\n{ctx_text}",
        )
        memory_msg.token_count = estimate_tokens(memory_msg.text)
        self._ctx.set_memory_messages([memory_msg])
