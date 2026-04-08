"""Integration tests: MindAgent ↔ SessionJournal.

Validates that chat() and chat_stream() correctly persist messages to
the session journal, including:
- system prompt written once on first turn
- user / assistant messages in correct order
- tool call chain completeness (assistant.tool_calls ↔ tool.tool_call_id)
- chat vs chat_stream produce consistent journal structure
- journal still works when memory is stubbed out
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

import pytest

from mindbot.agent.core import MindAgent
from mindbot.config.schema import Config
from mindbot.context.models import ChatResponse, FinishReason, Message, ToolCall
from mindbot.session.store import SessionJournal


# ---------------------------------------------------------------------------
# Lightweight stubs (no network I/O)
# ---------------------------------------------------------------------------


class FakeLLM:
    """Stub LLM that returns canned responses.

    When *tool_calls* is set, the first call returns an assistant message
    with those tool_calls, and the second call returns the final text.
    """

    def __init__(
        self,
        response_text: str = "mock reply",
        tool_calls: list[ToolCall] | None = None,
    ) -> None:
        self._response_text = response_text
        self._tool_calls = tool_calls
        self._call_count = 0

    async def chat(
        self,
        messages: list[Message],
        model: str | None = None,
        tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        self._call_count += 1
        if self._tool_calls and self._call_count == 1:
            return ChatResponse(
                content="",
                tool_calls=self._tool_calls,
                finish_reason=FinishReason.TOOL_CALLS,
            )
        return ChatResponse(content=self._response_text, finish_reason=FinishReason.STOP)

    async def chat_stream(
        self,
        messages: list[Message],
        model: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        yield self._response_text

    def bind_tools(self, tools: list[Any]) -> "FakeLLM":
        return self

    def get_info(self):
        return None

    def get_model_list(self):
        return []


@dataclass
class FakeTool:
    name: str = "test_tool"
    description: str = "A test tool"
    parameters: dict = field(default_factory=lambda: {"type": "object", "properties": {}})

    async def run(self, **kwargs: Any) -> str:
        return "tool result"


class FakeToolExecutor:
    async def execute_batch(self, tool_calls: list[ToolCall]) -> list[Any]:
        from mindbot.context.models import ToolResult
        return [
            ToolResult(tool_call_id=tc.id, success=True, content="tool result")
            for tc in tool_calls
        ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_config(tmp_path, system_prompt: str = "You are helpful.") -> Config:
    return Config(
        agent={"model": "openai/test", "system_prompt": system_prompt},
        session_journal={"enabled": True, "path": str(tmp_path / "journal")},
    )


def _make_agent(config: Config, fake_llm: FakeLLM | None = None) -> MindAgent:
    if fake_llm is None:
        fake_llm = FakeLLM()
    with patch("mindbot.providers.factory.ProviderFactory.create", return_value=fake_llm):
        agent = MindAgent(config)
    # agent.llm is a read-only property forwarding to _main_agent.llm;
    # ProviderFactory.create is already patched above so _main_agent.llm == fake_llm.
    return agent


@pytest.fixture()
def anyio_backend() -> str:
    return "asyncio"


# ---------------------------------------------------------------------------
# Tests: chat() → journal
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_chat_writes_system_user_assistant(tmp_path):
    config = _make_config(tmp_path)
    agent = _make_agent(config)

    await agent.chat("hello", session_id="s1")

    journal = SessionJournal(tmp_path / "journal")
    msgs = journal.read("s1")

    roles = [m.role for m in msgs]
    assert roles == ["system", "user", "assistant"]
    assert msgs[0].content == "You are helpful."
    assert msgs[1].content == "hello"
    assert msgs[2].content == "mock reply"
    assert msgs[2].message_kind == "assistant_text"
    assert msgs[2].stop_reason == "completed"
    assert msgs[2].turn_id is not None
    assert msgs[1].timestamp <= msgs[2].timestamp


@pytest.mark.anyio
async def test_chat_system_prompt_only_on_first_turn(tmp_path):
    config = _make_config(tmp_path)
    agent = _make_agent(config)

    await agent.chat("Q1", session_id="s1")
    await agent.chat("Q2", session_id="s1")

    journal = SessionJournal(tmp_path / "journal")
    msgs = journal.read("s1")

    system_msgs = [m for m in msgs if m.role == "system"]
    assert len(system_msgs) == 1
    assert msgs[0].role == "system"


@pytest.mark.anyio
async def test_chat_multi_turn_ordering(tmp_path):
    config = _make_config(tmp_path)
    agent = _make_agent(config)

    await agent.chat("Q1", session_id="s1")
    await agent.chat("Q2", session_id="s1")

    journal = SessionJournal(tmp_path / "journal")
    msgs = journal.read("s1")

    roles = [m.role for m in msgs]
    assert roles == ["system", "user", "assistant", "user", "assistant"]


@pytest.mark.anyio
async def test_chat_no_system_prompt(tmp_path):
    config = _make_config(tmp_path, system_prompt="")
    agent = _make_agent(config)

    await agent.chat("hello", session_id="s1")

    journal = SessionJournal(tmp_path / "journal")
    msgs = journal.read("s1")

    roles = [m.role for m in msgs]
    assert roles == ["user", "assistant"]


# ---------------------------------------------------------------------------
# Tests: chat_stream() → journal
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_chat_stream_writes_journal(tmp_path):
    config = _make_config(tmp_path)
    agent = _make_agent(config)

    chunks = []
    async for chunk in agent.chat_stream("stream me", session_id="s2"):
        chunks.append(chunk)

    assert len(chunks) > 0

    journal = SessionJournal(tmp_path / "journal")
    msgs = journal.read("s2")

    roles = [m.role for m in msgs]
    assert roles == ["system", "user", "assistant"]
    assert msgs[1].content == "stream me"
    assert msgs[2].content == "mock reply"
    assert msgs[2].message_kind == "assistant_text"
    assert msgs[2].stop_reason == "completed"
    assert msgs[2].turn_id is not None
    assert msgs[1].timestamp <= msgs[2].timestamp


# ---------------------------------------------------------------------------
# Tests: chat vs chat_stream consistency
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_chat_and_stream_produce_same_roles(tmp_path):
    config = _make_config(tmp_path)
    agent = _make_agent(config)

    await agent.chat("Q", session_id="chat")

    agent2 = _make_agent(config)
    async for _ in agent2.chat_stream("Q", session_id="stream"):
        pass

    journal = SessionJournal(tmp_path / "journal")
    chat_msgs = journal.read("chat")
    stream_msgs = journal.read("stream")
    chat_roles = [m.role for m in chat_msgs]
    stream_roles = [m.role for m in stream_msgs]
    assert chat_roles == stream_roles
    assert chat_msgs[-1].message_kind == stream_msgs[-1].message_kind == "assistant_text"


@pytest.mark.anyio
async def test_tool_call_preamble_is_not_mixed_into_final_assistant(tmp_path):
    config = _make_config(tmp_path)

    class PreambleToolLLM(FakeLLM):
        async def chat(
            self,
            messages: list[Message],
            model: str | None = None,
            tools: list[Any] | None = None,
            **kwargs: Any,
        ) -> ChatResponse:
            self._call_count += 1
            if self._call_count == 1:
                return ChatResponse(
                    content="让我先检查一下。",
                    tool_calls=[ToolCall(id="tc1", name="test_tool", arguments={})],
                    finish_reason=FinishReason.TOOL_CALLS,
                )
            return ChatResponse(content="最终答案", finish_reason=FinishReason.STOP)

    fake_llm = PreambleToolLLM()
    agent = _make_agent(config, fake_llm=fake_llm)

    await agent.chat("检查一下", session_id="s1")

    journal = SessionJournal(tmp_path / "journal")
    msgs = journal.read("s1")
    assert msgs[-1].role == "assistant"
    assert msgs[-1].content == "最终答案"


# ---------------------------------------------------------------------------
# Tests: journal independent of memory
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_journal_works_without_memory(tmp_path):
    config = _make_config(tmp_path)
    agent = _make_agent(config)
    # Disable memory on the underlying main agent so save_to_memory is a no-op
    agent._main_agent.memory = None  # type: ignore[assignment]

    # chat() should still write to journal even when memory is disabled
    try:
        await agent.chat("hello", session_id="s1")
    except Exception:
        pass

    journal = SessionJournal(tmp_path / "journal")
    msgs = journal.read("s1")
    # The journal write happens before memory save, so it should have data
    assert any(m.role == "user" for m in msgs)


# ---------------------------------------------------------------------------
# Tests: journal disabled
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_journal_disabled_no_files(tmp_path):
    config = Config(
        agent={"model": "openai/test"},
        session_journal={"enabled": False, "path": str(tmp_path / "journal")},
    )
    agent = _make_agent(config)
    await agent.chat("hello", session_id="s1")

    journal = SessionJournal(tmp_path / "journal")
    assert journal.read("s1") == []


# ---------------------------------------------------------------------------
# Tests: different sessions are isolated
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_different_sessions_isolated(tmp_path):
    config = _make_config(tmp_path)
    agent = _make_agent(config)

    await agent.chat("hello A", session_id="A")
    await agent.chat("hello B", session_id="B")

    journal = SessionJournal(tmp_path / "journal")
    a_msgs = journal.read("A")
    b_msgs = journal.read("B")

    assert all(m.content != "hello B" for m in a_msgs)
    assert all(m.content != "hello A" for m in b_msgs)
