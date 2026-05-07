"""Unit tests for agent.input_builder.InputBuilder.

Covers:
- async build(): block ordering, memory injection, intent_state placement
- memory recall integration (with / without MemoryManager)
- system prompt initialisation

After the Memory Recall refactor :class:`InputBuilder.build` is
``async`` and the memory pipeline returns
:class:`~mindbot.memory.types.MemoryHit` objects rather than plain
shards.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mindbot.agent.input_builder import InputBuilder
from mindbot.config.schema import ContextConfig, SkillsConfig
from mindbot.context.manager import ContextManager
from mindbot.memory.types import MemoryHit, MemoryShard
from mindbot.skills.models import SkillDefinition
from mindbot.skills.registry import SkillRegistry


# ---------------------------------------------------------------------------
# Lightweight stubs
# ---------------------------------------------------------------------------


def _make_hit(text: str, *, shard_id: str = "shard", score: float = 0.5) -> MemoryHit:
    shard = MemoryShard(id=shard_id, text=text)
    return MemoryHit(shard=shard, score=score, vector_score=score)


class FakeMemoryManager:
    def __init__(self, hits: list[MemoryHit] | None = None) -> None:
        self._hits = hits or []

    async def recall(
        self, query: str, top_k: int = 5, cluster_type: str | None = None,
    ) -> list[MemoryHit]:
        return self._hits[:top_k]

    def append_to_short_term(self, content: str, **kw: Any) -> list[Any]:
        return []


class FailingMemoryManager(FakeMemoryManager):
    async def recall(
        self, query: str, top_k: int = 5, cluster_type: str | None = None,
    ) -> list[MemoryHit]:
        raise RuntimeError("memory down")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def ctx() -> ContextManager:
    return ContextManager(ContextConfig(max_tokens=4000))


@pytest.fixture()
def memory_with_hits() -> FakeMemoryManager:
    return FakeMemoryManager([
        _make_hit("User likes Python", shard_id="c1", score=0.9),
        _make_hit("Previous topic: testing", shard_id="c2", score=0.6),
    ])


# ---------------------------------------------------------------------------
# build()
# ---------------------------------------------------------------------------


class TestBuild:

    async def test_basic_build_returns_user_message(self, ctx: ContextManager) -> None:
        builder = InputBuilder(context=ctx)
        msgs = await builder.build("hello")

        assert len(msgs) == 1
        assert msgs[-1].role == "user"
        assert msgs[-1].content == "hello"

    async def test_block_order_system_skills_memory_conversation_intent_user(
        self, ctx: ContextManager, memory_with_hits: FakeMemoryManager,
    ) -> None:
        ctx.set_system_identity("You are helpful.")
        ctx.add_conversation_message("user", "earlier")
        ctx.add_conversation_message("assistant", "earlier reply")
        registry = SkillRegistry.from_skills([
            SkillDefinition(
                name="python-helper",
                description="Answers Python questions",
                when_to_use="Use for Python programming questions",
                body="Prefer Python-specific guidance.",
                loaded_from="builtin",
                skill_dir=Path("/tmp/python-helper"),
            )
        ])

        builder = InputBuilder(
            context=ctx,
            memory=memory_with_hits,
            skill_registry=registry,
            skills_config=SkillsConfig(
                max_visible=4,
                max_detail_load=1,
                trigger_mode="explicit-only",
            ),
        )
        msgs = await builder.build("new question", intent_state="Be concise.")

        roles = [m.role for m in msgs]
        # system_identity, skills_overview, two memory shards (per-shard items),
        # conversation user/assistant, intent, user_input.
        assert roles[0] == "system"      # system_identity
        assert roles[1] == "system"      # skills_overview
        assert roles[2] == "system"      # memory shard #1
        assert roles[3] == "system"      # memory shard #2
        assert roles[4] == "user"        # conversation
        assert roles[5] == "assistant"   # conversation
        assert roles[6] == "system"      # intent_state
        assert roles[7] == "user"        # user_input
        assert msgs[-1].content == "new question"
        assert msgs[-2].content == "Be concise."

    async def test_intent_state_omitted_when_none(self, ctx: ContextManager) -> None:
        builder = InputBuilder(context=ctx, system_prompt="sys")
        msgs = await builder.build("hi")

        roles = [m.role for m in msgs]
        assert roles == ["system", "user"]

    async def test_memory_block_populated(
        self, ctx: ContextManager, memory_with_hits: FakeMemoryManager,
    ) -> None:
        builder = InputBuilder(context=ctx, memory=memory_with_hits)
        await builder.build("search query")

        mem_msgs = ctx.get_block("memory").messages
        assert len(mem_msgs) == 1
        assert "User likes Python" in mem_msgs[0].content

    async def test_memory_recall_failure_is_graceful(self, ctx: ContextManager) -> None:
        builder = InputBuilder(context=ctx, memory=FailingMemoryManager())
        msgs = await builder.build("hello")

        assert ctx.get_block("memory").messages == []
        assert len(msgs) >= 1

    async def test_system_prompt_sets_identity(self, ctx: ContextManager) -> None:
        builder = InputBuilder(context=ctx, system_prompt="I am a bot.")
        msgs = await builder.build("hello")

        assert msgs[0].role == "system"
        assert msgs[0].content == "I am a bot."

    async def test_user_input_block_refreshed_between_calls(self, ctx: ContextManager) -> None:
        builder = InputBuilder(context=ctx)

        await builder.build("first")
        assert ctx.get_block("user_input").messages[0].content == "first"

        await builder.build("second")
        assert len(ctx.get_block("user_input").messages) == 1
        assert ctx.get_block("user_input").messages[0].content == "second"

    async def test_context_property(self, ctx: ContextManager) -> None:
        builder = InputBuilder(context=ctx)
        assert builder.context is ctx

    async def test_reads_blocks_directly_not_via_prepare_for_llm(self, ctx: ContextManager) -> None:
        """InputBuilder should NOT call prepare_for_llm(); it reads blocks itself."""
        call_log: list[str] = []
        original = ctx.prepare_for_llm

        def tracking_prepare() -> list:
            call_log.append("prepare_for_llm")
            return original()

        ctx.prepare_for_llm = tracking_prepare  # type: ignore[assignment]

        builder = InputBuilder(context=ctx, system_prompt="sys")
        await builder.build("hello")
        assert "prepare_for_llm" not in call_log

    async def test_skills_blocks_populated_for_matching_query(self, ctx: ContextManager) -> None:
        registry = SkillRegistry.from_skills([
            SkillDefinition(
                name="python-helper",
                description="Answers Python questions",
                when_to_use="Use for Python programming questions",
                body="Prefer Python-specific guidance.",
                loaded_from="builtin",
                skill_dir=Path("/tmp/python-helper"),
            )
        ])
        builder = InputBuilder(
            context=ctx,
            skill_registry=registry,
            skills_config=SkillsConfig(max_visible=4, max_detail_load=1),
        )

        msgs = await builder.build("Need help with Python functions")

        assert "Available skills:" in ctx.get_block("skills_overview").messages[0].content
        assert "Selected skill: python-helper" in ctx.get_block("skills_detail").messages[0].content
        assert msgs[0].content.startswith("Available skills:")
        assert msgs[1].content.startswith("Selected skill:")

    async def test_skills_detail_omitted_when_nothing_matches(self, ctx: ContextManager) -> None:
        registry = SkillRegistry.from_skills([
            SkillDefinition(
                name="python-helper",
                description="Answers Python questions",
                when_to_use="Use for Python programming questions",
                body="Prefer Python-specific guidance.",
                loaded_from="builtin",
                skill_dir=Path("/tmp/python-helper"),
            )
        ])
        builder = InputBuilder(
            context=ctx,
            skill_registry=registry,
            skills_config=SkillsConfig(always_include=["python-helper"], max_visible=4, max_detail_load=1),
        )

        await builder.build("Tell me a joke")

        assert "Available skills:" in ctx.get_block("skills_overview").messages[0].content
        assert ctx.get_block("skills_detail").messages == []
