"""Unit tests for agent.scheduler.Scheduler (build-only compatibility shim).

Covers:
- assemble(): block ordering, memory injection, user_input placement
- build_messages(): preferred builder entrypoint and intent_state placement
- build(): alias for build_messages
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from mindbot.agent.scheduler import Scheduler
from mindbot.config.schema import ContextConfig
from mindbot.context.manager import ContextManager
from mindbot.context.models import Message


# ---------------------------------------------------------------------------
# Lightweight stubs (no real I/O)
# ---------------------------------------------------------------------------


@dataclass
class FakeMemoryChunk:
    text: str
    id: str = "chunk-1"


class FakeMemoryManager:
    """In-memory stub satisfying the MemoryManager read interface."""

    def __init__(self, chunks: list[FakeMemoryChunk] | None = None) -> None:
        self._chunks = chunks or []

    def search(self, query: str, top_k: int = 5, source: str | None = None) -> list[FakeMemoryChunk]:
        return self._chunks[:top_k]


class FailingMemoryManager(FakeMemoryManager):
    """A MemoryManager whose search always raises."""

    def search(self, query: str, top_k: int = 5, source: str | None = None) -> list[FakeMemoryChunk]:
        raise RuntimeError("memory down")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def ctx() -> ContextManager:
    return ContextManager(ContextConfig(max_tokens=4000))


@pytest.fixture()
def memory_with_chunks() -> FakeMemoryManager:
    return FakeMemoryManager([
        FakeMemoryChunk(text="User likes Python", id="c1"),
        FakeMemoryChunk(text="Previous topic: testing", id="c2"),
    ])


@pytest.fixture()
def empty_memory() -> FakeMemoryManager:
    return FakeMemoryManager([])


# ---------------------------------------------------------------------------
# assemble()
# ---------------------------------------------------------------------------


class TestAssemble:

    def test_basic_assembly_returns_user_message(self, ctx: ContextManager) -> None:
        scheduler = Scheduler(context=ctx)
        msgs = scheduler.assemble("hello")

        assert len(msgs) == 1
        assert msgs[-1].role == "user"
        assert msgs[-1].content == "hello"

    def test_block_order_system_memory_conversation_user(
        self, ctx: ContextManager, memory_with_chunks: FakeMemoryManager,
    ) -> None:
        ctx.set_system_identity("You are a helpful assistant.")
        ctx.add_conversation_message("user", "earlier question")
        ctx.add_conversation_message("assistant", "earlier answer")

        scheduler = Scheduler(context=ctx, memory=memory_with_chunks)
        msgs = scheduler.assemble("new question")

        roles = [m.role for m in msgs]
        assert roles[0] == "system"                # system_identity
        assert roles[1] == "system"                # memory block
        assert roles[2] == "user"                  # conversation: earlier question
        assert roles[3] == "assistant"             # conversation: earlier answer
        assert roles[-1] == "user"                 # user_input: new question
        assert msgs[-1].content == "new question"

    def test_memory_block_populated_from_manager(
        self, ctx: ContextManager, memory_with_chunks: FakeMemoryManager,
    ) -> None:
        scheduler = Scheduler(context=ctx, memory=memory_with_chunks)
        msgs = scheduler.assemble("search query")

        memory_msgs = ctx.get_block("memory").messages
        assert len(memory_msgs) == 1
        assert "User likes Python" in memory_msgs[0].content
        assert "Previous topic: testing" in memory_msgs[0].content

    def test_memory_block_empty_when_no_manager(self, ctx: ContextManager) -> None:
        scheduler = Scheduler(context=ctx, memory=None)
        scheduler.assemble("hello")
        assert ctx.get_block("memory").messages == []

    def test_memory_block_empty_when_no_results(
        self, ctx: ContextManager, empty_memory: FakeMemoryManager,
    ) -> None:
        scheduler = Scheduler(context=ctx, memory=empty_memory)
        scheduler.assemble("hello")
        assert ctx.get_block("memory").messages == []

    def test_memory_search_failure_is_graceful(self, ctx: ContextManager) -> None:
        scheduler = Scheduler(context=ctx, memory=FailingMemoryManager())
        msgs = scheduler.assemble("hello")

        assert ctx.get_block("memory").messages == []
        assert len(msgs) >= 1

    def test_memory_top_k_respected(self, ctx: ContextManager) -> None:
        many_chunks = FakeMemoryManager([
            FakeMemoryChunk(text=f"fact-{i}", id=f"c{i}") for i in range(10)
        ])
        scheduler = Scheduler(context=ctx, memory=many_chunks, memory_top_k=3)
        scheduler.assemble("hello")

        mem_content = ctx.get_block("memory").messages[0].content
        assert mem_content.count("- fact-") == 3

    def test_system_prompt_sets_identity(self, ctx: ContextManager) -> None:
        scheduler = Scheduler(context=ctx, system_prompt="I am a bot.")
        msgs = scheduler.assemble("hello")

        assert msgs[0].role == "system"
        assert msgs[0].content == "I am a bot."

    def test_user_input_block_cleared_between_calls(self, ctx: ContextManager) -> None:
        scheduler = Scheduler(context=ctx)

        scheduler.assemble("first")
        assert ctx.get_block("user_input").messages[0].content == "first"

        scheduler.assemble("second")
        assert len(ctx.get_block("user_input").messages) == 1
        assert ctx.get_block("user_input").messages[0].content == "second"

    def test_build_messages_includes_intent_state_before_user_input(self, ctx: ContextManager) -> None:
        scheduler = Scheduler(context=ctx)
        ctx.set_system_identity("You are a helpful assistant.")
        ctx.add_conversation_message("user", "earlier question")

        msgs = scheduler.build_messages("new question", intent_state="User wants a concise answer.")

        assert [msg.role for msg in msgs] == ["system", "user", "system", "user"]
        assert msgs[-2].content == "User wants a concise answer."
        assert msgs[-1].content == "new question"
        assert ctx.get_block("intent_state").messages[0].content == "User wants a concise answer."

    def test_build_is_alias_of_build_messages(self, ctx: ContextManager) -> None:
        scheduler = Scheduler(context=ctx)
        msgs = scheduler.build("hello")

        assert len(msgs) == 1
        assert msgs[0].content == "hello"


# ---------------------------------------------------------------------------
# Integration: multi-turn assemble cycle
# ---------------------------------------------------------------------------


class TestFullCycle:

    def test_assemble_after_manual_history_reflects_conversation(self, ctx: ContextManager) -> None:
        scheduler = Scheduler(context=ctx)

        scheduler.assemble("q1")
        ctx.add_conversation_message("user", "q1")
        ctx.add_conversation_message("assistant", "a1")
        ctx.clear_user_input()

        msgs = scheduler.assemble("q2")
        contents = [m.content for m in msgs]
        assert "q1" in contents
        assert "a1" in contents
        assert contents[-1] == "q2"
