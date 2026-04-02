"""Regression tests for the Agent/MindAgent architecture refactoring.

Covers:
- Agent: LRU session eviction (max_sessions)
- Agent: tool signature invalidation on same-name replacement
- MindAgent: supervisor with child agent registry
- MultiAgentOrchestrator: sequential and parallel modes
- Config: max_sessions field present and defaults to 1000
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mindbot.agent.agent import Agent
from mindbot.agent.core import MindAgent
from mindbot.agent.multi_agent import MultiAgentOrchestrator
from mindbot.config.schema import AgentConfig, Config, ContextConfig
from mindbot.context.models import ChatResponse, FinishReason, Message


# ---------------------------------------------------------------------------
# Lightweight stubs
# ---------------------------------------------------------------------------


class FakeLLM:
    """Minimal LLM stub that returns a fixed reply."""

    def __init__(self, reply: str = "ok") -> None:
        self._reply = reply
        self.chat_calls: list[list[Message]] = []
        self.stream_calls: list[list[Message]] = []

    async def chat(
        self,
        messages: list[Message],
        model: str | None = None,
        tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        self.chat_calls.append(messages)
        return ChatResponse(content=self._reply, finish_reason=FinishReason.STOP)

    async def chat_stream(
        self,
        messages: list[Message],
        model: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        self.stream_calls.append(messages)
        yield self._reply

    def bind_tools(self, tools: list[Any]) -> "FakeLLM":
        return self

    def get_info(self) -> None:
        return None

    def get_model_list(self) -> list:
        return []


@dataclass
class FakeTool:
    name: str
    description: str = "A test tool"
    parameters: dict = field(default_factory=lambda: {"type": "object", "properties": {}})

    async def run(self, **kwargs: Any) -> str:
        return f"result_of_{self.name}"


def _make_agent(name: str = "test", reply: str = "ok") -> tuple[Agent, FakeLLM]:
    """Build a minimal Agent backed by a FakeLLM (no real I/O)."""
    llm = FakeLLM(reply=reply)
    agent = Agent(
        name=name,
        llm=llm,
        context_config=ContextConfig(max_tokens=4000),
        max_sessions=3,  # small limit for eviction tests
    )
    return agent, llm


# ---------------------------------------------------------------------------
# Agent: LRU session eviction
# ---------------------------------------------------------------------------


class TestAgentLRUEviction:

    def test_sessions_below_limit_all_retained(self) -> None:
        agent, _ = _make_agent()
        agent._max_sessions = 5
        for i in range(5):
            agent._get_session_context(f"s{i}")
        assert len(agent._sessions) == 5

    def test_oldest_session_evicted_when_limit_exceeded(self) -> None:
        agent, _ = _make_agent()
        agent._max_sessions = 3
        agent._get_session_context("first")
        agent._get_session_context("second")
        agent._get_session_context("third")
        # Access "first" to make it recently used
        agent._get_session_context("first")
        # Adding "fourth" should evict "second" (oldest unused)
        agent._get_session_context("fourth")

        assert "second" not in agent._sessions
        assert "first" in agent._sessions
        assert "third" in agent._sessions
        assert "fourth" in agent._sessions

    def test_turn_engine_evicted_with_session(self) -> None:
        agent, _ = _make_agent()
        agent._max_sessions = 2
        agent._get_session_context("s1")
        agent._turn_engines["s1"] = MagicMock()
        agent._turn_engine_tool_signatures["s1"] = frozenset()

        agent._get_session_context("s2")
        agent._get_session_context("s3")  # evicts s1

        assert "s1" not in agent._sessions
        assert "s1" not in agent._turn_engines
        assert "s1" not in agent._turn_engine_tool_signatures

    @pytest.mark.asyncio
    async def test_chat_maintains_lru_order(self) -> None:
        agent, llm = _make_agent()
        agent._max_sessions = 3
        await agent.chat("msg", session_id="A")
        await agent.chat("msg", session_id="B")
        await agent.chat("msg", session_id="C")
        # Touch A again
        await agent.chat("msg", session_id="A")
        # Add D → should evict B (oldest)
        await agent.chat("msg", session_id="D")

        assert "B" not in agent._sessions
        assert "A" in agent._sessions


# ---------------------------------------------------------------------------
# Agent: tool signature invalidation
# ---------------------------------------------------------------------------


class TestToolSignatureInvalidation:

    def test_same_name_different_object_produces_different_signature(self) -> None:
        agent, _ = _make_agent()
        tool_v1 = FakeTool(name="calc")
        tool_v2 = FakeTool(name="calc")  # same name, different object

        sig1 = agent._get_tool_signature([tool_v1])
        sig2 = agent._get_tool_signature([tool_v2])
        assert sig1 != sig2

    def test_same_object_produces_same_signature(self) -> None:
        agent, _ = _make_agent()
        tool = FakeTool(name="calc")
        assert agent._get_tool_signature([tool]) == agent._get_tool_signature([tool])

    def test_different_names_produce_different_signatures(self) -> None:
        agent, _ = _make_agent()
        t1 = FakeTool(name="a")
        t2 = FakeTool(name="b")
        assert agent._get_tool_signature([t1]) != agent._get_tool_signature([t2])

    @pytest.mark.asyncio
    async def test_turn_engine_rebuilt_on_tool_replacement(self) -> None:
        """After register_tool() with same name, the next chat rebuilds turn engine."""
        agent, llm = _make_agent()
        tool_v1 = FakeTool(name="search")
        agent.register_tool(tool_v1)

        await agent.chat("find me", session_id="sess")
        engine_first = agent._turn_engines.get("sess")
        sig_first = agent._turn_engine_tool_signatures.get("sess")

        # Replace with a new object of the same name
        tool_v2 = FakeTool(name="search")
        agent.tool_registry._tools.clear()  # type: ignore[attr-defined]
        agent.tool_registry.register(tool_v2)

        await agent.chat("find me again", session_id="sess")
        engine_second = agent._turn_engines.get("sess")
        sig_second = agent._turn_engine_tool_signatures.get("sess")

        assert engine_first is not engine_second, "TurnEngine must be rebuilt on tool replacement"
        assert sig_first != sig_second


# ---------------------------------------------------------------------------
# MindAgent: supervisor with child agents
# ---------------------------------------------------------------------------


def _make_mindagent(tmp_path: Any, reply: str = "supervisor ok") -> tuple[MindAgent, FakeLLM]:
    """Create a MindAgent with a patched LLM (no real network or DB)."""
    fake_llm = FakeLLM(reply=reply)
    config = Config(
        agent={"model": "openai/test", "system_prompt": ""},
        session_journal={"enabled": False},
        memory={"storage_path": str(tmp_path / "mem.db")},
    )
    with patch("mindbot.providers.factory.ProviderFactory.create", return_value=fake_llm):
        agent = MindAgent(config)
    return agent, fake_llm


class TestMindAgentSupervisor:

    def test_register_and_get_child_agent(self, tmp_path: Any) -> None:
        supervisor, _ = _make_mindagent(tmp_path)
        child_llm = FakeLLM(reply="child ok")
        child = Agent(
            name="child1",
            llm=child_llm,
            context_config=ContextConfig(max_tokens=2000),
        )
        supervisor.register_child_agent(child)

        assert supervisor.get_child_agent("child1") is child
        assert len(supervisor.list_child_agents()) == 1

    def test_get_unknown_child_returns_none(self, tmp_path: Any) -> None:
        supervisor, _ = _make_mindagent(tmp_path)
        assert supervisor.get_child_agent("nonexistent") is None

    def test_main_agent_tool_registry_forwarded(self, tmp_path: Any) -> None:
        supervisor, _ = _make_mindagent(tmp_path)
        tool = FakeTool(name="ping")
        supervisor.register_tool(tool)
        assert any(t.name == "ping" for t in supervisor.list_tools())
        assert any(t.name == "ping" for t in supervisor._main_agent.list_tools())

    @pytest.mark.asyncio
    async def test_chat_delegates_to_main_agent(self, tmp_path: Any) -> None:
        supervisor, fake_llm = _make_mindagent(tmp_path, reply="supervisor reply")
        response = await supervisor.chat("hello", session_id="s1")
        assert response.content == "supervisor reply"

    def test_llm_property_returns_main_agent_llm(self, tmp_path: Any) -> None:
        supervisor, fake_llm = _make_mindagent(tmp_path)
        assert supervisor.llm is fake_llm

    # ------------------------------------------------------------------
# MultiAgentOrchestrator
# ---------------------------------------------------------------------------


class TestMultiAgentOrchestrator:

    @pytest.mark.asyncio
    async def test_sequential_uses_main_agent(self) -> None:
        orchestrator = MultiAgentOrchestrator()
        llm1 = FakeLLM(reply="main response")
        llm2 = FakeLLM(reply="worker response")
        main = Agent(name="main", llm=llm1, context_config=ContextConfig(max_tokens=2000))
        worker = Agent(name="worker", llm=llm2, context_config=ContextConfig(max_tokens=2000))
        orchestrator.set_main_agent(main)
        orchestrator.register_agent(worker)

        response = await orchestrator.execute("do task", mode="sequential")
        assert response.content == "main response"

    @pytest.mark.asyncio
    async def test_sequential_falls_back_to_first_registered(self) -> None:
        orchestrator = MultiAgentOrchestrator()
        llm = FakeLLM(reply="first agent")
        agent = Agent(name="only", llm=llm, context_config=ContextConfig(max_tokens=2000))
        orchestrator.register_agent(agent)

        response = await orchestrator.execute("task")
        assert response.content == "first agent"

    @pytest.mark.asyncio
    async def test_parallel_runs_all_agents_concurrently(self) -> None:
        orchestrator = MultiAgentOrchestrator()
        for i in range(3):
            llm = FakeLLM(reply=f"reply_{i}")
            agent = Agent(
                name=f"agent{i}",
                llm=llm,
                context_config=ContextConfig(max_tokens=2000),
            )
            orchestrator.register_agent(agent)

        response = await orchestrator.execute("task", mode="parallel")
        # Combined output should contain all three replies
        for i in range(3):
            assert f"reply_{i}" in response.content
        assert "---" in response.content  # separator between results

    @pytest.mark.asyncio
    async def test_parallel_sessions_are_namespaced(self) -> None:
        """Each agent in parallel mode gets a namespaced session to avoid collisions."""
        orchestrator = MultiAgentOrchestrator()
        captured_sessions: list[str] = []

        class TrackingLLM(FakeLLM):
            pass

        agents = []
        for i in range(2):
            llm = FakeLLM(reply="ok")
            a = Agent(name=f"a{i}", llm=llm, context_config=ContextConfig(max_tokens=2000))
            orchestrator.register_agent(a)
            agents.append(a)

        await orchestrator.execute("task", session_id="base", mode="parallel")

        # Each agent should have its own namespaced session key
        for a in agents:
            expected_key = f"base::{a.name}"
            assert expected_key in a._sessions

    @pytest.mark.asyncio
    async def test_no_agents_raises(self) -> None:
        orchestrator = MultiAgentOrchestrator()
        with pytest.raises(RuntimeError, match="No agents registered"):
            await orchestrator.execute("task")

    @pytest.mark.asyncio
    async def test_unknown_mode_raises(self) -> None:
        orchestrator = MultiAgentOrchestrator()
        agent = Agent(
            name="a",
            llm=FakeLLM(),
            context_config=ContextConfig(max_tokens=2000),
        )
        orchestrator.register_agent(agent)
        with pytest.raises(ValueError, match="Unknown mode"):
            await orchestrator.execute("task", mode="unknown")


# ---------------------------------------------------------------------------
# Config: max_sessions field
# ---------------------------------------------------------------------------


class TestConfigMaxSessions:

    def test_default_max_sessions_is_1000(self) -> None:
        cfg = AgentConfig()
        assert cfg.max_sessions == 1000

    def test_custom_max_sessions_persists(self) -> None:
        cfg = AgentConfig(max_sessions=500)
        assert cfg.max_sessions == 500

    def test_max_sessions_propagated_to_agent(self, tmp_path: Any) -> None:
        fake_llm = FakeLLM()
        config = Config(
            agent={"model": "openai/test", "max_sessions": 42},
            session_journal={"enabled": False},
            memory={"storage_path": str(tmp_path / "mem.db")},
        )
        with patch("mindbot.providers.factory.ProviderFactory.create", return_value=fake_llm):
            supervisor = MindAgent(config)
        assert supervisor._main_agent._max_sessions == 42
