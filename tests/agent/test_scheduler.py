"""Unit tests for agent.scheduler.Scheduler (build-only compatibility shim).

Covers:
- assemble(): block ordering, memory injection, user_input placement
- build_messages(): preferred builder entrypoint and intent_state placement
- build(): alias for build_messages

After the Memory Recall refactor every Scheduler build entrypoint is
``async`` and the memory pipeline returns
:class:`~mindbot.memory.types.MemoryHit` objects.
"""

from __future__ import annotations

import pytest

from mindbot.agent.scheduler import Scheduler
from mindbot.config.schema import ContextConfig
from mindbot.context.manager import ContextManager
from mindbot.memory.types import MemoryHit, MemoryShard


# ---------------------------------------------------------------------------
# Lightweight stubs (no real I/O)
# ---------------------------------------------------------------------------


def _hit(text: str, *, shard_id: str = "c1", score: float = 0.5) -> MemoryHit:
    return MemoryHit(
        shard=MemoryShard(id=shard_id, text=text), score=score, vector_score=score,
    )


class FakeMemoryManager:
    """In-memory stub satisfying the MemoryManager async interface."""

    def __init__(self, hits: list[MemoryHit] | None = None) -> None:
        self._hits = hits or []

    async def recall(
        self, query: str, top_k: int = 5, cluster_type: str | None = None,
    ) -> list[MemoryHit]:
        return self._hits[:top_k]


class FailingMemoryManager(FakeMemoryManager):
    """A MemoryManager whose recall always raises."""

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
        _hit("User likes Python", shard_id="c1", score=0.9),
        _hit("Previous topic: testing", shard_id="c2", score=0.6),
    ])


@pytest.fixture()
def empty_memory() -> FakeMemoryManager:
    return FakeMemoryManager([])


# ---------------------------------------------------------------------------
# assemble()
# ---------------------------------------------------------------------------


class TestAssemble:

    async def test_basic_assembly_returns_user_message(self, ctx: ContextManager) -> None:
        scheduler = Scheduler(context=ctx)
        msgs = await scheduler.assemble("hello")

        assert len(msgs) == 1
        assert msgs[-1].role == "user"
        assert msgs[-1].content == "hello"

    async def test_block_order_system_memory_conversation_user(
        self, ctx: ContextManager, memory_with_hits: FakeMemoryManager,
    ) -> None:
        ctx.set_system_identity("You are a helpful assistant.")
        ctx.add_conversation_message("user", "earlier question")
        ctx.add_conversation_message("assistant", "earlier answer")

        scheduler = Scheduler(context=ctx, memory=memory_with_hits)
        msgs = await scheduler.assemble("new question")

        roles = [m.role for m in msgs]
        # system_identity, two memory shards, conversation user/assistant, new user.
        assert roles[0] == "system"                # system_identity
        assert roles[1] == "system"                # memory shard 1
        assert roles[2] == "system"                # memory shard 2
        assert roles[3] == "user"                  # conversation: earlier question
        assert roles[4] == "assistant"             # conversation: earlier answer
        assert roles[-1] == "user"                 # user_input: new question
        assert msgs[-1].content == "new question"

    async def test_memory_block_populated_from_manager(
        self, ctx: ContextManager, memory_with_hits: FakeMemoryManager,
    ) -> None:
        scheduler = Scheduler(context=ctx, memory=memory_with_hits)
        await scheduler.assemble("search query")

        memory_msgs = ctx.get_block("memory").messages
        assert len(memory_msgs) == 1
        assert "User likes Python" in memory_msgs[0].content
        assert "Previous topic: testing" in memory_msgs[0].content

    async def test_memory_block_empty_when_no_manager(self, ctx: ContextManager) -> None:
        scheduler = Scheduler(context=ctx, memory=None)
        await scheduler.assemble("hello")
        assert ctx.get_block("memory").messages == []

    async def test_memory_block_empty_when_no_results(
        self, ctx: ContextManager, empty_memory: FakeMemoryManager,
    ) -> None:
        scheduler = Scheduler(context=ctx, memory=empty_memory)
        await scheduler.assemble("hello")
        assert ctx.get_block("memory").messages == []

    async def test_memory_recall_failure_is_graceful(self, ctx: ContextManager) -> None:
        scheduler = Scheduler(context=ctx, memory=FailingMemoryManager())
        msgs = await scheduler.assemble("hello")

        assert ctx.get_block("memory").messages == []
        assert len(msgs) >= 1

    async def test_memory_top_k_respected(self, ctx: ContextManager) -> None:
        many_hits = FakeMemoryManager([
            _hit(f"fact-{i}", shard_id=f"c{i}", score=1.0 - i * 0.05)
            for i in range(10)
        ])
        scheduler = Scheduler(context=ctx, memory=many_hits, memory_top_k=3)
        await scheduler.assemble("hello")

        mem_content = ctx.get_block("memory").messages[0].content
        assert mem_content.count("- fact-") == 3

    async def test_system_prompt_sets_identity(self, ctx: ContextManager) -> None:
        scheduler = Scheduler(context=ctx, system_prompt="I am a bot.")
        msgs = await scheduler.assemble("hello")

        assert msgs[0].role == "system"
        assert msgs[0].content == "I am a bot."

    async def test_user_input_block_cleared_between_calls(self, ctx: ContextManager) -> None:
        scheduler = Scheduler(context=ctx)

        await scheduler.assemble("first")
        assert ctx.get_block("user_input").messages[0].content == "first"

        await scheduler.assemble("second")
        assert len(ctx.get_block("user_input").messages) == 1
        assert ctx.get_block("user_input").messages[0].content == "second"

    async def test_build_messages_includes_intent_state_before_user_input(
        self, ctx: ContextManager,
    ) -> None:
        scheduler = Scheduler(context=ctx)
        ctx.set_system_identity("You are a helpful assistant.")
        ctx.add_conversation_message("user", "earlier question")

        msgs = await scheduler.build_messages(
            "new question", intent_state="User wants a concise answer.",
        )

        assert [msg.role for msg in msgs] == ["system", "user", "system", "user"]
        assert msgs[-2].content == "User wants a concise answer."
        assert msgs[-1].content == "new question"
        assert ctx.get_block("intent_state").messages[0].content == "User wants a concise answer."

    async def test_build_is_alias_of_build_messages(self, ctx: ContextManager) -> None:
        scheduler = Scheduler(context=ctx)
        msgs = await scheduler.build("hello")

        assert len(msgs) == 1
        assert msgs[0].content == "hello"


# ---------------------------------------------------------------------------
# Integration: multi-turn assemble cycle
# ---------------------------------------------------------------------------


class TestFullCycle:

    async def test_assemble_after_manual_history_reflects_conversation(
        self, ctx: ContextManager,
    ) -> None:
        scheduler = Scheduler(context=ctx)

        await scheduler.assemble("q1")
        ctx.add_conversation_message("user", "q1")
        ctx.add_conversation_message("assistant", "a1")
        ctx.clear_user_input()

        msgs = await scheduler.assemble("q2")
        contents = [m.content for m in msgs]
        assert "q1" in contents
        assert "a1" in contents
        assert contents[-1] == "q2"
