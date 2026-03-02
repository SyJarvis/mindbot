"""Unit tests for session.store.SessionJournal.

Covers:
- append / read round-trip
- system prompt written once on first turn
- multi-turn user/assistant ordering
- tool call chain completeness (assistant.tool_calls ↔ tool.tool_call_id)
- list_sessions / session_exists
- malformed line handling
- empty / nonexistent session
- file persistence across instances
"""

from __future__ import annotations

import json
import time

import pytest

from mindbot.session.store import SessionJournal
from mindbot.session.types import SessionMessage


@pytest.fixture()
def journal(tmp_path):
    return SessionJournal(tmp_path / "journal")


# ------------------------------------------------------------------
# Basic round-trip
# ------------------------------------------------------------------

def test_append_and_read(journal: SessionJournal):
    msgs = [
        SessionMessage(role="user", content="hello"),
        SessionMessage(role="assistant", content="hi there"),
    ]
    journal.append("s1", msgs)

    result = journal.read("s1")
    assert len(result) == 2
    assert result[0].role == "user"
    assert result[0].content == "hello"
    assert result[1].role == "assistant"
    assert result[1].content == "hi there"


def test_read_nonexistent_session(journal: SessionJournal):
    assert journal.read("no-such") == []


def test_empty_append_is_noop(journal: SessionJournal):
    journal.append("s1", [])
    assert journal.read("s1") == []
    assert not journal.session_exists("s1")


# ------------------------------------------------------------------
# System prompt first-turn
# ------------------------------------------------------------------

def test_system_prompt_first_turn(journal: SessionJournal):
    journal.append("s1", [
        SessionMessage(role="system", content="You are helpful."),
        SessionMessage(role="user", content="hi"),
        SessionMessage(role="assistant", content="hello"),
    ])
    result = journal.read("s1")
    assert result[0].role == "system"
    assert result[0].content == "You are helpful."
    assert result[1].role == "user"


# ------------------------------------------------------------------
# Multi-turn ordering
# ------------------------------------------------------------------

def test_multi_turn_ordering(journal: SessionJournal):
    """Appending across multiple turns preserves chronological order."""
    journal.append("s1", [
        SessionMessage(role="system", content="sys"),
        SessionMessage(role="user", content="Q1"),
        SessionMessage(role="assistant", content="A1"),
    ])
    journal.append("s1", [
        SessionMessage(role="user", content="Q2"),
        SessionMessage(role="assistant", content="A2"),
    ])
    result = journal.read("s1")
    roles = [m.role for m in result]
    assert roles == ["system", "user", "assistant", "user", "assistant"]
    assert result[3].content == "Q2"
    assert result[4].content == "A2"


# ------------------------------------------------------------------
# Tool call chain completeness
# ------------------------------------------------------------------

def test_tool_call_chain(journal: SessionJournal):
    """assistant.tool_calls and tool.tool_call_id form a traceable chain."""
    msgs = [
        SessionMessage(role="user", content="what time is it?"),
        SessionMessage(
            role="assistant",
            content="",
            tool_calls=[{"id": "tc_1", "name": "get_time", "arguments": {}}],
        ),
        SessionMessage(
            role="tool",
            content="2026-03-02T10:30:00Z",
            tool_call_id="tc_1",
        ),
        SessionMessage(role="assistant", content="It is 10:30 UTC."),
    ]
    journal.append("s1", msgs)
    result = journal.read("s1")

    assert len(result) == 4
    assert result[1].tool_calls is not None
    assert result[1].tool_calls[0]["id"] == "tc_1"
    assert result[2].role == "tool"
    assert result[2].tool_call_id == "tc_1"


def test_multi_tool_calls_per_turn(journal: SessionJournal):
    """Multiple parallel tool calls in a single assistant message."""
    msgs = [
        SessionMessage(role="user", content="get weather and time"),
        SessionMessage(
            role="assistant",
            content="",
            tool_calls=[
                {"id": "tc_a", "name": "get_weather", "arguments": {"city": "NYC"}},
                {"id": "tc_b", "name": "get_time", "arguments": {}},
            ],
        ),
        SessionMessage(role="tool", content="Sunny 25°C", tool_call_id="tc_a"),
        SessionMessage(role="tool", content="10:30 UTC", tool_call_id="tc_b"),
        SessionMessage(role="assistant", content="NYC is sunny at 10:30 UTC."),
    ]
    journal.append("s1", msgs)
    result = journal.read("s1")

    tc_ids = {m.tool_call_id for m in result if m.role == "tool"}
    assistant_tc_ids = {tc["id"] for tc in result[1].tool_calls}
    assert tc_ids == assistant_tc_ids


# ------------------------------------------------------------------
# list_sessions / session_exists
# ------------------------------------------------------------------

def test_list_sessions(journal: SessionJournal):
    journal.append("alpha", [SessionMessage(role="user", content="a")])
    journal.append("beta", [SessionMessage(role="user", content="b")])
    assert set(journal.list_sessions()) == {"alpha", "beta"}


def test_session_exists(journal: SessionJournal):
    assert not journal.session_exists("x")
    journal.append("x", [SessionMessage(role="user", content="hi")])
    assert journal.session_exists("x")


# ------------------------------------------------------------------
# Malformed / edge cases
# ------------------------------------------------------------------

def test_malformed_lines_skipped(journal: SessionJournal):
    """Corrupt lines are skipped without crashing."""
    path = journal._session_path("bad")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"role": "user", "content": "good", "timestamp": 1.0}) + "\n")
        fh.write("NOT-JSON\n")
        fh.write(json.dumps({"role": "assistant", "content": "also good", "timestamp": 2.0}) + "\n")

    result = journal.read("bad")
    assert len(result) == 2
    assert result[0].content == "good"
    assert result[1].content == "also good"


# ------------------------------------------------------------------
# File persistence across instances
# ------------------------------------------------------------------

def test_persistence_across_instances(tmp_path):
    """Data survives creating a new SessionJournal instance on the same path."""
    j1 = SessionJournal(tmp_path / "j")
    j1.append("s1", [
        SessionMessage(role="user", content="hello"),
        SessionMessage(role="assistant", content="world"),
    ])

    j2 = SessionJournal(tmp_path / "j")
    result = j2.read("s1")
    assert len(result) == 2
    assert result[1].content == "world"


# ------------------------------------------------------------------
# SessionMessage serialisation
# ------------------------------------------------------------------

def test_to_dict_drops_none(journal: SessionJournal):
    msg = SessionMessage(role="user", content="hi")
    d = msg.to_dict()
    assert "tool_calls" not in d
    assert "tool_call_id" not in d
    assert "reasoning_content" not in d


def test_from_dict_ignores_unknown_keys():
    d = {"role": "user", "content": "hi", "timestamp": 1.0, "extra_field": True}
    msg = SessionMessage.from_dict(d)
    assert msg.role == "user"
    assert msg.content == "hi"


def test_reasoning_content_round_trip(journal: SessionJournal):
    msgs = [SessionMessage(
        role="assistant",
        content="answer",
        reasoning_content="let me think...",
    )]
    journal.append("s1", msgs)
    result = journal.read("s1")
    assert result[0].reasoning_content == "let me think..."
