"""Unit tests for agent.scheduler.Scheduler.

Covers:
- assemble(): block ordering, memory injection, user_input placement
- commit(): conversation persistence, user_input clearing
- commit_messages(): bulk-commit
- tool persistence strategies (none / summary / full)
- memory population (with / without MemoryManager)
- save_to_memory()
- get_tools()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from mindbot.agent.scheduler import Scheduler
from mindbot.config.schema import ContextConfig
from mindbot.context.manager import ContextManager
from mindbot.context.models import Message, ToolCall


# ---------------------------------------------------------------------------
# Lightweight stubs (no real I/O)
# ---------------------------------------------------------------------------


@dataclass
class FakeMemoryChunk:
    text: str
    id: str = "chunk-1"


class FakeMemoryManager:
    """In-memory stub satisfying the MemoryManager read/write interface."""

    def __init__(self, chunks: list[FakeMemoryChunk] | None = None) -> None:
        self._chunks = chunks or []
        self.short_term_writes: list[str] = []

    def search(self, query: str, top_k: int = 5, source: str | None = None) -> list[FakeMemoryChunk]:
        return self._chunks[:top_k]

    def append_to_short_term(self, content: str, **kwargs: Any) -> list[Any]:
        self.short_term_writes.append(content)
        return []


class FailingMemoryManager(FakeMemoryManager):
    """A MemoryManager whose search always raises."""

    def search(self, query: str, top_k: int = 5, source: str | None = None) -> list[FakeMemoryChunk]:
        raise RuntimeError("memory down")


@dataclass
class FakeTool:
    name: str = "test_tool"
    description: str = "A test tool"


class FakeToolRegistry:
    """Minimal stub for ToolRegistry."""

    def __init__(self, tools: list[FakeTool] | None = None) -> None:
        self._tools = tools or []

    def list_tools(self) -> list[FakeTool]:
        return list(self._tools)


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


# ---------------------------------------------------------------------------
# commit()
# ---------------------------------------------------------------------------


class TestCommit:

    def test_commit_appends_user_and_assistant(self, ctx: ContextManager) -> None:
        scheduler = Scheduler(context=ctx)
        scheduler.assemble("hi")
        scheduler.commit("hi", "hello there")

        conv = ctx.get_block("conversation").messages
        assert len(conv) == 2
        assert conv[0].role == "user"
        assert conv[0].content == "hi"
        assert conv[1].role == "assistant"
        assert conv[1].content == "hello there"

    def test_commit_clears_user_input_block(self, ctx: ContextManager) -> None:
        scheduler = Scheduler(context=ctx)
        scheduler.assemble("hi")
        assert len(ctx.get_block("user_input").messages) == 1

        scheduler.commit("hi", "response")
        assert ctx.get_block("user_input").messages == []

    def test_multi_turn_conversation_accumulates(self, ctx: ContextManager) -> None:
        scheduler = Scheduler(context=ctx)

        scheduler.assemble("turn 1")
        scheduler.commit("turn 1", "reply 1")

        scheduler.assemble("turn 2")
        scheduler.commit("turn 2", "reply 2")

        conv = ctx.get_block("conversation").messages
        assert len(conv) == 4
        assert conv[0].content == "turn 1"
        assert conv[1].content == "reply 1"
        assert conv[2].content == "turn 2"
        assert conv[3].content == "reply 2"


# ---------------------------------------------------------------------------
# commit_messages()
# ---------------------------------------------------------------------------


class TestCommitMessages:

    def test_bulk_commit_skips_system(self, ctx: ContextManager) -> None:
        scheduler = Scheduler(context=ctx)
        scheduler.assemble("q")

        msgs = [
            Message(role="user", content="q"),
            Message(role="system", content="should be skipped"),
            Message(role="assistant", content="a"),
        ]
        scheduler.commit_messages(msgs)

        conv = ctx.get_block("conversation").messages
        roles = [m.role for m in conv]
        assert "system" not in roles
        assert len(conv) == 2

    def test_bulk_commit_clears_user_input(self, ctx: ContextManager) -> None:
        scheduler = Scheduler(context=ctx)
        scheduler.assemble("q")
        scheduler.commit_messages([Message(role="user", content="q")])
        assert ctx.get_block("user_input").messages == []


# ---------------------------------------------------------------------------
# Tool persistence strategies
# ---------------------------------------------------------------------------


class TestToolPersistence:

    @staticmethod
    def _make_tool_messages() -> list[Message]:
        return [
            Message(
                role="assistant",
                content="Let me check.",
                tool_calls=[ToolCall(id="tc1", name="get_weather", arguments={"city": "Beijing"})],
            ),
            Message(role="tool", content="22C cloudy", tool_call_id="tc1"),
        ]

    def test_none_strategy_drops_tool_messages(self, ctx: ContextManager) -> None:
        scheduler = Scheduler(context=ctx, tool_persistence="none")
        scheduler.assemble("weather?")
        scheduler.commit("weather?", "It's 22C.", extra_messages=self._make_tool_messages())

        conv = ctx.get_block("conversation").messages
        roles = [m.role for m in conv]
        assert "tool" not in roles
        assert len(conv) == 2  # user + assistant only

    def test_full_strategy_keeps_all_tool_messages(self, ctx: ContextManager) -> None:
        scheduler = Scheduler(context=ctx, tool_persistence="full")
        scheduler.assemble("weather?")
        scheduler.commit("weather?", "It's 22C.", extra_messages=self._make_tool_messages())

        conv = ctx.get_block("conversation").messages
        roles = [m.role for m in conv]
        assert "assistant" in roles
        assert "tool" in roles
        assert len(conv) == 4  # user + tool_assistant + tool_result + final_assistant

    def test_summary_strategy_collapses_to_system_note(self, ctx: ContextManager) -> None:
        scheduler = Scheduler(context=ctx, tool_persistence="summary")
        scheduler.assemble("weather?")
        scheduler.commit("weather?", "It's 22C.", extra_messages=self._make_tool_messages())

        conv = ctx.get_block("conversation").messages
        roles = [m.role for m in conv]
        assert "tool" not in roles

        system_notes = [m for m in conv if m.role == "system"]
        assert len(system_notes) == 1
        assert "get_weather" in system_notes[0].content

    def test_no_extra_messages_works_for_all_strategies(self, ctx: ContextManager) -> None:
        for strategy in ("none", "summary", "full"):
            local_ctx = ContextManager(ContextConfig(max_tokens=4000))
            scheduler = Scheduler(context=local_ctx, tool_persistence=strategy)  # type: ignore[arg-type]
            scheduler.assemble("hi")
            scheduler.commit("hi", "hello")

            conv = local_ctx.get_block("conversation").messages
            assert len(conv) == 2


# ---------------------------------------------------------------------------
# save_to_memory()
# ---------------------------------------------------------------------------


class TestSaveToMemory:

    def test_writes_user_and_assistant(
        self, ctx: ContextManager, empty_memory: FakeMemoryManager,
    ) -> None:
        scheduler = Scheduler(context=ctx, memory=empty_memory)
        scheduler.save_to_memory("hello", "hi there")

        assert len(empty_memory.short_term_writes) == 2
        assert "User: hello" in empty_memory.short_term_writes[0]
        assert "Assistant: hi there" in empty_memory.short_term_writes[1]

    def test_no_op_without_memory_manager(self, ctx: ContextManager) -> None:
        scheduler = Scheduler(context=ctx, memory=None)
        scheduler.save_to_memory("hello", "hi there")  # should not raise


# ---------------------------------------------------------------------------
# get_tools()
# ---------------------------------------------------------------------------


class TestGetTools:

    def test_returns_empty_without_registry(self, ctx: ContextManager) -> None:
        scheduler = Scheduler(context=ctx)
        assert scheduler.get_tools() == []

    def test_returns_tools_from_registry(self, ctx: ContextManager) -> None:
        tools = [FakeTool(name="a"), FakeTool(name="b")]
        scheduler = Scheduler(context=ctx, tool_registry=FakeToolRegistry(tools))
        result = scheduler.get_tools()
        assert len(result) == 2
        assert {t.name for t in result} == {"a", "b"}


# ---------------------------------------------------------------------------
# Integration: full assemble -> commit cycle
# ---------------------------------------------------------------------------


class TestFullCycle:

    def test_two_turn_conversation_with_memory(self, ctx: ContextManager) -> None:
        memory = FakeMemoryManager([FakeMemoryChunk(text="user prefers Chinese")])
        scheduler = Scheduler(context=ctx, memory=memory, system_prompt="You are MindBot.")

        # Turn 1
        msgs1 = scheduler.assemble("hello")
        assert msgs1[0].role == "system"
        assert msgs1[0].content == "You are MindBot."
        assert any("user prefers Chinese" in m.content for m in msgs1)
        assert msgs1[-1].content == "hello"

        scheduler.commit("hello", "Hi! How can I help?")
        scheduler.save_to_memory("hello", "Hi! How can I help?")

        # Turn 2
        msgs2 = scheduler.assemble("tell me a joke")
        conv_msgs = [m for m in msgs2 if m.role in ("user", "assistant") and m.content != "tell me a joke"]
        assert len(conv_msgs) == 2  # previous turn in conversation block
        assert msgs2[-1].content == "tell me a joke"

        scheduler.commit("tell me a joke", "Why did the chicken cross the road?")

        conv = ctx.get_block("conversation").messages
        assert len(conv) == 4

    def test_assemble_after_commit_reflects_history(self, ctx: ContextManager) -> None:
        scheduler = Scheduler(context=ctx)

        scheduler.assemble("q1")
        scheduler.commit("q1", "a1")

        msgs = scheduler.assemble("q2")
        contents = [m.content for m in msgs]
        assert "q1" in contents
        assert "a1" in contents
        assert contents[-1] == "q2"
