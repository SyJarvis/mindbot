"""Unit tests for agent.persistence_writer.PersistenceWriter.

Covers:
- commit_turn: conversation context, memory, journal
- tool_persistence strategies (none / summary / full)
- journal writes (system prompt on first session, trace backfill)
- single commit_turn per turn guarantee
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

import pytest

from mindbot.agent.models import AgentResponse
from mindbot.agent.persistence_writer import PersistenceWriter
from mindbot.config.schema import ContextConfig
from mindbot.context.manager import ContextManager
from mindbot.context.models import Message, ProviderInfo, ToolCall, UsageInfo


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class FakeMemoryManager:
    def __init__(self) -> None:
        self.writes: list[str] = []

    def append_to_short_term(self, content: str, **kw: Any) -> list[Any]:
        self.writes.append(content)
        return []


class FailingMemory(FakeMemoryManager):
    def append_to_short_term(self, content: str, **kw: Any) -> list[Any]:
        raise RuntimeError("memory down")


@dataclass
class FakeJournalEntry:
    session_id: str
    messages: list[Any]


class FakeJournal:
    def __init__(self) -> None:
        self.entries: list[FakeJournalEntry] = []

    def append(self, session_id: str, messages: Sequence[Any]) -> None:
        self.entries.append(FakeJournalEntry(session_id, list(messages)))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def ctx() -> ContextManager:
    return ContextManager(ContextConfig(max_tokens=4000))


@pytest.fixture()
def memory() -> FakeMemoryManager:
    return FakeMemoryManager()


@pytest.fixture()
def journal() -> FakeJournal:
    return FakeJournal()


def _make_response(content: str = "answer", trace: list[Message] | None = None) -> AgentResponse:
    return AgentResponse(content=content, message_trace=trace or [])


# ---------------------------------------------------------------------------
# Conversation context
# ---------------------------------------------------------------------------


class TestConversationCommit:

    def test_commit_turn_writes_user_and_assistant(self, ctx: ContextManager) -> None:
        writer = PersistenceWriter(context=ctx)
        writer.commit_turn("hello", _make_response("hi there"))

        conv = ctx.get_block("conversation").messages
        assert len(conv) == 2
        assert conv[0].role == "user"
        assert conv[0].content == "hello"
        assert conv[1].role == "assistant"
        assert conv[1].content == "hi there"

    def test_commit_clears_user_input_and_intent(self, ctx: ContextManager) -> None:
        ctx.set_user_input(Message(role="user", content="q"))
        ctx.set_intent_state("some intent")
        writer = PersistenceWriter(context=ctx)
        writer.commit_turn("q", _make_response("a"))

        assert ctx.get_block("user_input").messages == []
        assert ctx.get_block("intent_state").messages == []


# ---------------------------------------------------------------------------
# Tool persistence strategies
# ---------------------------------------------------------------------------


class TestToolPersistence:

    @staticmethod
    def _make_trace() -> list[Message]:
        return [
            Message(
                role="assistant",
                content="Let me check.",
                tool_calls=[ToolCall(id="tc1", name="get_weather", arguments={"city": "Beijing"})],
            ),
            Message(role="tool", content="22C cloudy", tool_call_id="tc1"),
        ]

    def test_none_drops_tool_messages(self, ctx: ContextManager) -> None:
        writer = PersistenceWriter(context=ctx, tool_persistence="none")
        writer.commit_turn("weather?", _make_response("22C.", self._make_trace()))

        conv = ctx.get_block("conversation").messages
        roles = [m.role for m in conv]
        assert "tool" not in roles
        assert len(conv) == 2  # user + assistant

    def test_full_keeps_all_tool_messages(self, ctx: ContextManager) -> None:
        writer = PersistenceWriter(context=ctx, tool_persistence="full")
        trace = self._make_trace() + [
            Message(role="assistant", content="22C.", message_kind="assistant_text"),
        ]
        writer.commit_turn("weather?", _make_response("22C.", trace))

        conv = ctx.get_block("conversation").messages
        roles = [m.role for m in conv]
        assert "assistant" in roles
        assert "tool" in roles
        assert len(conv) == 4
        assert conv[-1].content == "22C."

    def test_summary_collapses_to_system_note(self, ctx: ContextManager) -> None:
        writer = PersistenceWriter(context=ctx, tool_persistence="summary")
        writer.commit_turn("weather?", _make_response("22C.", self._make_trace()))

        conv = ctx.get_block("conversation").messages
        system_notes = [m for m in conv if m.role == "system"]
        assert len(system_notes) == 1
        assert "get_weather" in system_notes[0].content


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


class TestMemoryCommit:

    def test_writes_user_and_assistant_to_memory(
        self, ctx: ContextManager, memory: FakeMemoryManager,
    ) -> None:
        writer = PersistenceWriter(context=ctx, memory=memory)
        writer.commit_turn("hello", _make_response("world"))

        assert len(memory.writes) == 2
        assert "User: hello" in memory.writes[0]
        assert "Assistant: world" in memory.writes[1]

    def test_no_op_without_memory(self, ctx: ContextManager) -> None:
        writer = PersistenceWriter(context=ctx, memory=None)
        writer.commit_turn("hello", _make_response("world"))

    def test_memory_failure_is_graceful(self, ctx: ContextManager) -> None:
        writer = PersistenceWriter(context=ctx, memory=FailingMemory())
        writer.commit_turn("hello", _make_response("world"))


# ---------------------------------------------------------------------------
# Journal
# ---------------------------------------------------------------------------


class TestJournalCommit:

    def test_writes_to_journal(
        self, ctx: ContextManager, journal: FakeJournal,
    ) -> None:
        writer = PersistenceWriter(context=ctx, journal=journal)
        writer.commit_turn("hello", _make_response("world"), session_id="s1")

        assert len(journal.entries) == 1
        entry = journal.entries[0]
        assert entry.session_id == "s1"
        roles = [m.role for m in entry.messages]
        assert "user" in roles
        assert "assistant" in roles

    def test_system_prompt_written_on_first_session_only(
        self, ctx: ContextManager, journal: FakeJournal,
    ) -> None:
        writer = PersistenceWriter(
            context=ctx, journal=journal, system_prompt="You are helpful.",
        )
        writer.commit_turn("q1", _make_response("a1"), session_id="s1")
        writer.commit_turn("q2", _make_response("a2"), session_id="s1")

        all_roles = [m.role for e in journal.entries for m in e.messages]
        assert all_roles.count("system") == 1

    def test_trace_included_in_journal(
        self, ctx: ContextManager, journal: FakeJournal,
    ) -> None:
        trace = [
            Message(
                role="assistant",
                content="check",
                tool_calls=[ToolCall(id="tc1", name="search", arguments={})],
                turn_id="turn-1",
                iteration=0,
                message_kind="assistant_tool_call",
                provider=ProviderInfo(provider="openai", model="gpt-test"),
                usage=UsageInfo(prompt_tokens=11, completion_tokens=3, total_tokens=14),
                finish_reason="tool_calls",
            ),
            Message(
                role="tool",
                content="found it",
                tool_call_id="tc1",
                turn_id="turn-1",
                iteration=0,
                message_kind="tool_result",
                tool_name="search",
            ),
            Message(
                role="assistant",
                content="Here.",
                turn_id="turn-1",
                iteration=1,
                message_kind="assistant_text",
                stop_reason="completed",
            ),
        ]
        writer = PersistenceWriter(context=ctx, journal=journal)
        writer.commit_turn("find", _make_response("Here.", trace), session_id="s1")

        entry = journal.entries[0]
        roles = [m.role for m in entry.messages]
        assert "tool" in roles
        assistant_tool_msg = entry.messages[1]
        tool_msg = entry.messages[2]
        final_msg = entry.messages[3]
        assert assistant_tool_msg.turn_id == "turn-1"
        assert assistant_tool_msg.message_kind == "assistant_tool_call"
        assert assistant_tool_msg.provider == {
            "provider": "openai",
            "model": "gpt-test",
            "supports_vision": False,
            "supports_tools": False,
        }
        assert assistant_tool_msg.usage == {
            "prompt_tokens": 11,
            "completion_tokens": 3,
            "total_tokens": 14,
        }
        assert tool_msg.tool_name == "search"
        assert final_msg.stop_reason == "completed"

    def test_no_journal_is_no_op(self, ctx: ContextManager) -> None:
        writer = PersistenceWriter(context=ctx, journal=None)
        writer.commit_turn("hello", _make_response("world"), session_id="s1")

    def test_commit_journal_turn_supports_streaming_style_writes(
        self, ctx: ContextManager, journal: FakeJournal,
    ) -> None:
        writer = PersistenceWriter(
            context=ctx,
            journal=journal,
            system_prompt="You are helpful.",
        )

        writer.commit_journal_turn("stream me", "world", session_id="s1")

        assert len(journal.entries) == 1
        msgs = journal.entries[0].messages
        assert [m.role for m in msgs] == ["system", "user", "assistant"]
        assert msgs[-1].content == "world"


# ---------------------------------------------------------------------------
# Integration: single commit_turn per turn
# ---------------------------------------------------------------------------


class TestSingleCommit:

    def test_two_turns_accumulate_correctly(self, ctx: ContextManager) -> None:
        writer = PersistenceWriter(context=ctx)

        writer.commit_turn("turn1", _make_response("reply1"))
        writer.commit_turn("turn2", _make_response("reply2"))

        conv = ctx.get_block("conversation").messages
        assert len(conv) == 4
        assert conv[0].content == "turn1"
        assert conv[1].content == "reply1"
        assert conv[2].content == "turn2"
        assert conv[3].content == "reply2"
