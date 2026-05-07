"""Phase B input builder – assembles per-turn LLM messages.

The ``InputBuilder`` reads from :class:`~mindbot.context.manager.ContextManager`
(blocks) and :class:`~mindbot.memory.manager.MemoryManager` (retrieval) to
produce the final ``list[Message]`` sent to the LLM each turn.

The builder collects :class:`~mindbot.context.items.ContextItem`
candidates from each information source (system identity, skills,
memory, conversation, intent, user input) and hands them to a
:class:`~mindbot.context.packer.ContextPacker`, which decides what to
keep based on attention scores and the current token budget.  Block
state on the :class:`~mindbot.context.manager.ContextManager` is still
updated for persistence and observability, but the final prompt no
longer comes from concatenating raw blocks.

Tool definitions are **not** injected here — they are passed via
``ProviderAdapter.bind_tools()`` at the LLM call site.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from mindbot.context.items import ContextItem
from mindbot.context.manager import ContextManager
from mindbot.context.models import Message, MessageContent
from mindbot.context.packer import ContextPacker
from mindbot.utils import estimate_tokens

if TYPE_CHECKING:
    from mindbot.config.schema import SkillsConfig
    from mindbot.memory.manager import MemoryManager
    from mindbot.memory.types import MemoryHit, MemoryShard
    from mindbot.skills.registry import SkillRegistry

from mindbot.skills.render import render_skills_detail, render_skills_overview
from mindbot.skills.selector import SkillSelector
from mindbot.logging import logger


# ---------------------------------------------------------------------------
# Priority tiers (informal cognitive analogy in comments)
# ---------------------------------------------------------------------------

# Higher priority items are placed before lower-priority items when the
# packer competes for the available token budget.  These priorities
# capture the intent that:
#
#   - Identity/system prompt and the current user input are always in
#     working memory (sensory + executive grounding).
#   - Skill detail (procedural memory selected for the task) and
#     retrieved long-term memory are critical task context.
#   - Skill overview is a lightweight catalog – nice to have but easily
#     dropped.
#   - Intent state is a turn-scoped goal hint.
#   - Conversation history is the most flexible; it has the lowest
#     priority but a strong compression callback so it almost always
#     fits with at least the most recent turns.

_PRIORITY = {
    "system": 100,
    "user": 100,
    "skill_detail": 70,
    "memory": 60,
    "skill_overview": 50,
    "intent": 50,
    "conversation": 40,
}


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

    The builder mirrors recently-collected information into the
    underlying :class:`~mindbot.context.manager.ContextManager` so other
    subsystems (persistence, checkpoints, debugging) keep observing
    consistent state, but the final ``list[Message]`` is produced by a
    :class:`~mindbot.context.packer.ContextPacker` that competes
    candidate items for the current token budget.
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
        packer: ContextPacker | None = None,
        response_reserve: int | None = None,
    ) -> None:
        self._ctx = context
        self._memory = memory
        self._memory_top_k = memory_top_k
        self._skill_registry = skill_registry
        self._skills_config = skills_config
        self._packer = packer or ContextPacker()
        self._response_reserve = response_reserve

        # Per-turn caches populated during build() so collect helpers can
        # share state without re-running expensive operations.
        self._latest_hits: list["MemoryHit"] = []

        if system_prompt:
            self._ctx.set_system_identity(system_prompt)

    @property
    def context(self) -> ContextManager:
        """The underlying context manager (shared state)."""
        return self._ctx

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    async def build(
        self,
        user_input: str | MessageContent,
        *,
        session_id: str | None = None,
        intent_state: str | None = None,
    ) -> list[Message]:
        """Build the final message list for one LLM call.

        Steps:
        1. Refresh skills overview/detail blocks for the current query.
        2. Recall memory hits via the hybrid retriever (vector + FTS +
           grep + index + recency) and cache them as per-shard items.
        3. Update intent and user-input blocks on the context manager.
        4. Collect :class:`ContextItem` candidates from every source.
        5. Run the :class:`ContextPacker` against the configured token
           budget and return the assembled messages.
        """
        t0 = time.perf_counter()

        query_text = (
            user_input if isinstance(user_input, str) else _extract_text(user_input)
        )

        self._populate_skills_blocks(query_text)
        await self._populate_memory_block(query_text)
        await self._ctx.maybe_compact()
        self._ctx.set_intent_state(intent_state)

        user_msg = Message(role="user", content=user_input)
        user_msg.token_count = estimate_tokens(user_msg.text)
        self._ctx.set_user_input(user_msg)

        items = self._collect_items()
        result = self._packer.pack(
            items,
            total_budget=self._ctx.max_tokens,
            response_reserve=self._response_reserve,
        )

        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info(
            "input_builder.build: msgs={} tokens={}/{} items={} elapsed_ms={:.1f}",
            len(result.messages),
            result.token_count,
            result.budget,
            len(result.items),
            elapsed_ms,
        )
        logger.debug("input_builder.pack_decisions: {}", result.summary())

        return result.messages

    # ------------------------------------------------------------------
    # Candidate collection
    # ------------------------------------------------------------------

    def _collect_items(self) -> list[ContextItem]:
        """Collect every information source as a :class:`ContextItem`."""
        items: list[ContextItem] = []

        items.extend(self._system_items())
        items.extend(self._skill_items())
        items.extend(self._memory_items())
        items.extend(self._conversation_items())
        items.extend(self._intent_items())
        items.extend(self._user_items())

        return items

    def _system_items(self) -> list[ContextItem]:
        msgs = self._ctx.get_block_messages("system_identity")
        if not msgs:
            return []
        return [
            ContextItem(
                name="system_identity",
                source="system",
                messages=list(msgs),
                priority=_PRIORITY["system"],
                salience=1.0,
                required=True,
                cache_scope="global",
                compress=_truncate_messages_factory(msgs),
            )
        ]

    def _skill_items(self) -> list[ContextItem]:
        items: list[ContextItem] = []

        overview = self._ctx.get_block_messages("skills_overview")
        if overview:
            items.append(
                ContextItem(
                    name="skills_overview",
                    source="skill_overview",
                    messages=list(overview),
                    priority=_PRIORITY["skill_overview"],
                    salience=0.6,
                    cache_scope="session",
                    compress=_truncate_messages_factory(overview),
                )
            )

        detail = self._ctx.get_block_messages("skills_detail")
        if detail:
            items.append(
                ContextItem(
                    name="skills_detail",
                    source="skill_detail",
                    messages=list(detail),
                    priority=_PRIORITY["skill_detail"],
                    salience=0.8,
                    cache_scope="turn",
                    compress=_truncate_messages_factory(detail),
                )
            )

        return items

    def _memory_items(self) -> list[ContextItem]:
        """One :class:`ContextItem` per recalled shard.

        Promoting each :class:`~mindbot.memory.types.MemoryHit` to its
        own ``ContextItem`` lets the packer compete shards individually:
        a high-similarity vector hit can survive a tight budget while a
        marginal grep-only hit is dropped or compressed.
        """
        hits = self._latest_hits
        if not hits:
            return []

        max_score = max(hit.score for hit in hits) or 1.0

        items: list[ContextItem] = []
        for hit in hits:
            shard = hit.shard
            shard_id = shard.id or "shard"
            full_msg = _render_shard_message(shard)
            items.append(
                ContextItem(
                    name=f"memory:{shard_id[:8]}",
                    source="memory",
                    messages=[full_msg],
                    priority=_PRIORITY["memory"],
                    salience=_combine_salience(hit, max_score=max_score),
                    cache_scope="turn",
                    compress=_shard_message_compress(shard),
                    metadata={
                        "score": hit.score,
                        "vector_score": hit.vector_score,
                        "fts_score": hit.fts_score,
                        "grep_score": hit.grep_score,
                        "index_score": hit.index_score,
                        "recency_score": hit.recency_score,
                        "reason": hit.reason,
                        "shard_id": shard_id,
                    },
                )
            )
        return items

    def _conversation_items(self) -> list[ContextItem]:
        msgs = self._ctx.get_block_messages("conversation")
        if not msgs:
            return []
        return [
            ContextItem(
                name="conversation",
                source="conversation",
                messages=list(msgs),
                priority=_PRIORITY["conversation"],
                salience=0.5,
                cache_scope="session",
                compress=_conversation_compress(msgs),
            )
        ]

    def _intent_items(self) -> list[ContextItem]:
        msgs = self._ctx.get_block_messages("intent_state")
        if not msgs:
            return []
        return [
            ContextItem(
                name="intent_state",
                source="intent",
                messages=list(msgs),
                priority=_PRIORITY["intent"],
                salience=0.7,
                cache_scope="turn",
                compress=_truncate_messages_factory(msgs),
            )
        ]

    def _user_items(self) -> list[ContextItem]:
        msgs = self._ctx.get_block_messages("user_input")
        if not msgs:
            return []
        return [
            ContextItem(
                name="user_input",
                source="user",
                messages=list(msgs),
                priority=_PRIORITY["user"],
                salience=1.0,
                required=True,
                cache_scope="turn",
                compress=_truncate_messages_factory(msgs),
            )
        ]

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

    async def _populate_memory_block(self, query: str) -> None:
        """Recall memories via the hybrid retriever and stage them.

        The full :class:`MemoryHit` list is cached in
        ``self._latest_hits`` so :meth:`_memory_items` can promote each
        shard to its own :class:`ContextItem`.  The :class:`ContextManager`
        ``memory`` block is still populated with a single rendered
        message for persistence and observability.
        """
        self._latest_hits = []

        if self._memory is None:
            self._ctx.set_memory_messages([])
            return

        hits: list[MemoryHit] = []
        try:
            hits = await self._memory.recall(query, top_k=self._memory_top_k)
        except Exception as exc:
            logger.debug("Memory recall failed: {}", exc)

        if not hits:
            self._ctx.set_memory_messages([])
            return

        self._latest_hits = list(hits)
        shards = [hit.shard for hit in hits]
        memory_msg = _render_memory_message(shards)
        self._ctx.set_memory_messages([memory_msg])


# ---------------------------------------------------------------------------
# Compression helpers
# ---------------------------------------------------------------------------

def _truncate_messages_factory(messages: list[Message]):
    """Return a compress callback that truncates by last-message text."""
    snapshot = list(messages)

    def _compress(target: int) -> list[Message]:
        return _truncate_to_budget(snapshot, target)

    return _compress


def _truncate_to_budget(messages: list[Message], target: int) -> list[Message]:
    """Keep messages from the end that fit within *target* tokens."""
    if target <= 0 or not messages:
        return []

    kept: list[Message] = []
    used = 0
    for msg in reversed(messages):
        cost = msg.token_count if msg.token_count > 0 else estimate_tokens(msg.text)
        if used + cost > target:
            break
        kept.append(msg)
        used += cost

    kept.reverse()
    if kept or not messages:
        return kept

    # Nothing fit – shrink the last message by character so something
    # survives.  This is what would otherwise be dropped entirely.
    last = messages[-1]
    text = last.text if isinstance(last.content, str) else ""
    if not text:
        return []

    while text:
        cut = max(1, len(text) // 8)
        text = text[: max(0, len(text) - cut)]
        if not text:
            return []
        if estimate_tokens(text) <= target:
            shrunk = Message(role=last.role, content=text)
            shrunk.tool_calls = last.tool_calls
            shrunk.reasoning_content = last.reasoning_content
            shrunk.tool_call_id = last.tool_call_id
            shrunk.token_count = estimate_tokens(text)
            return [shrunk]
    return []


def _conversation_compress(messages: list[Message]):
    """Compress callback for conversation – truncation + recency."""
    from mindbot.context.compression import _truncate_messages_sync
    snapshot = list(messages)

    def _compress(target: int) -> list[Message]:
        if target <= 0:
            return []
        compressed = _truncate_messages_sync(snapshot, target)
        for m in compressed:
            if m.token_count <= 0:
                m.token_count = estimate_tokens(m.text)
        return compressed

    return _compress


def _shard_message_compress(shard: "MemoryShard"):
    """Compress callback that truncates a single shard's text to *target*."""

    def _compress(target: int) -> list[Message]:
        if target <= 0:
            return []
        msg = _render_shard_message(shard)
        if msg.token_count <= target:
            return [msg]
        text = msg.text
        while text:
            cut = max(1, len(text) // 8)
            text = text[: max(0, len(text) - cut)]
            if not text:
                return []
            if estimate_tokens(text) <= target:
                shrunk = Message(role=msg.role, content=text)
                shrunk.token_count = estimate_tokens(text)
                return [shrunk]
        return []

    return _compress


def _render_memory_message(shards: list["MemoryShard"]) -> Message:
    """Render a list of shards into a single system message (block view)."""
    lines = "\n".join(f"- {s.text}" for s in shards)
    msg = Message(
        role="system",
        content=f"Relevant context from memory:\n{lines}",
    )
    msg.token_count = estimate_tokens(msg.text)
    return msg


def _render_shard_message(shard: "MemoryShard") -> Message:
    """Render a single shard as one ``system`` message for packing."""
    msg = Message(role="system", content=f"- {shard.text}")
    msg.token_count = estimate_tokens(msg.text)
    return msg


def _combine_salience(hit: "MemoryHit", *, max_score: float = 1.0) -> float:
    """Per-shard salience combining retrieval signals + shard metadata.

    Formula::

        salience = retrieval * 0.55
                 + recency   * 0.15
                 + access    * 0.10
                 + permanence* 0.10
                 + confidence* 0.10

    where ``retrieval`` is the hit's combined ``score`` normalised by
    the strongest hit in the current recall, and ``recency`` is the
    retriever's recency signal (already normalised).  Access count is
    saturated at 10 visits, permanence is binary, and confidence
    defaults to 1.0 when absent on the shard.
    """
    shard = hit.shard
    retrieval = max(0.0, min(hit.score / max_score, 1.0)) if max_score > 0 else 0.0
    recency = max(0.0, min(hit.recency_score, 1.0))
    access = min(getattr(shard, "access_count", 0) / 10.0, 1.0)
    permanence = 1.0 if getattr(shard, "is_permanent", False) else 0.0
    confidence = float(getattr(shard, "confidence", 1.0))
    salience = (
        retrieval * 0.55
        + recency * 0.15
        + access * 0.10
        + permanence * 0.10
        + confidence * 0.10
    )
    return max(0.0, min(salience, 1.0))
