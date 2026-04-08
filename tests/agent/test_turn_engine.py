"""Unit tests for agent.turn_engine.TurnEngine.

Covers:
- message_trace: no-tool, one-tool, multi-tool, tool-failure, repeated-tool
- authoritative trace includes final assistant message on no-tool turns
- stop reasons
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from collections.abc import AsyncIterator

import pytest

from mindbot.agent.models import AgentEvent, AgentResponse, StopReason
from mindbot.agent.turn_engine import TurnEngine
from mindbot.context.models import ChatResponse, FinishReason, Message, ProviderInfo, ToolCall, UsageInfo


# ---------------------------------------------------------------------------
# Fake LLM adapter
# ---------------------------------------------------------------------------


class FakeLLMAdapter:
    """A controllable LLM adapter that returns pre-configured responses."""

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = list(responses)
        self._call_idx = 0

    async def chat(self, messages: list[Message], tools: list[Any] | None = None, **kw: Any) -> ChatResponse:
        resp = self._responses[self._call_idx]
        self._call_idx += 1
        return resp

    async def chat_stream(self, messages: list[Message], **kw: Any) -> AsyncIterator[str]:
        resp = self._responses[self._call_idx]
        self._call_idx += 1
        if resp.content:
            yield resp.content

    def bind_tools(self, tools: list[Any]) -> "FakeLLMAdapter":
        return self


@pytest.fixture()
def anyio_backend() -> str:
    return "asyncio"


# ---------------------------------------------------------------------------
# Fake tool for capability facade
# ---------------------------------------------------------------------------


class FakeCapabilityFacade:
    """Returns a fixed string result for any tool call."""

    def __init__(self, results: dict[str, str] | None = None) -> None:
        self._results = results or {}

    async def resolve_and_execute(self, query: Any, arguments: dict[str, Any], context: dict[str, Any] | None = None) -> str:
        return self._results.get(query.name, f"result for {query.name}")

    def resolve(self, query: Any) -> Any:
        pass

    def list_capabilities(self) -> list:
        return []


# ---------------------------------------------------------------------------
# Fake tool model (needed for bind_tools in TurnEngine)
# ---------------------------------------------------------------------------


@dataclass
class FakeTool:
    name: str = "weather"
    description: str = "Get weather"

    def parameters_json_schema(self) -> dict:
        return {"type": "object", "properties": {"city": {"type": "string"}}}


# ---------------------------------------------------------------------------
# No-tool turn
# ---------------------------------------------------------------------------


class TestNoToolTurn:

    @pytest.mark.anyio
    async def test_no_tool_trace_includes_final_assistant(self) -> None:
        llm = FakeLLMAdapter([
            ChatResponse(
                content="Hello!",
                tool_calls=None,
                finish_reason=FinishReason.STOP,
                provider=ProviderInfo(provider="openai", model="gpt-test"),
                usage=UsageInfo(prompt_tokens=5, completion_tokens=2, total_tokens=7),
            ),
        ])
        engine = TurnEngine(llm=llm)
        msgs = [Message(role="user", content="hi")]

        response = await engine.run(messages=msgs)

        assert response.stop_reason == StopReason.COMPLETED
        assert response.content == "Hello!"
        assert len(response.message_trace) == 1
        trace_msg = response.message_trace[0]
        assert trace_msg.role == "assistant"
        assert trace_msg.content == "Hello!"
        assert trace_msg.message_kind == "assistant_text"
        assert trace_msg.finish_reason == "stop"
        assert trace_msg.stop_reason == StopReason.COMPLETED.value
        assert trace_msg.turn_id is not None

    @pytest.mark.anyio
    async def test_no_tool_empty_content(self) -> None:
        llm = FakeLLMAdapter([
            ChatResponse(content="", tool_calls=None, finish_reason="stop"),
        ])
        engine = TurnEngine(llm=llm)
        msgs = [Message(role="user", content="hi")]

        response = await engine.run(messages=msgs)

        assert response.stop_reason == StopReason.COMPLETED
        assert response.message_trace == []


# ---------------------------------------------------------------------------
# One-tool turn
# ---------------------------------------------------------------------------


class TestOneToolTurn:

    @pytest.mark.anyio
    async def test_one_tool_trace_has_assistant_tool_final(self) -> None:
        tool_call = ToolCall(id="tc1", name="weather", arguments={"city": "Beijing"})
        llm = FakeLLMAdapter([
            ChatResponse(
                content="",
                tool_calls=[tool_call],
                finish_reason=FinishReason.TOOL_CALLS,
                provider=ProviderInfo(provider="openai", model="gpt-test"),
                usage=UsageInfo(prompt_tokens=10, completion_tokens=3, total_tokens=13),
            ),
            ChatResponse(
                content="It's 22C in Beijing.",
                tool_calls=None,
                finish_reason=FinishReason.STOP,
                provider=ProviderInfo(provider="openai", model="gpt-test"),
                usage=UsageInfo(prompt_tokens=12, completion_tokens=4, total_tokens=16),
            ),
        ])
        facade = FakeCapabilityFacade({"weather": "22C cloudy"})
        engine = TurnEngine(llm=llm, tools=[FakeTool()], capability_facade=facade)
        msgs = [Message(role="user", content="weather?")]

        response = await engine.run(messages=msgs)

        assert response.stop_reason == StopReason.COMPLETED
        assert "22C" in response.content

        trace = response.message_trace
        assert len(trace) >= 3
        assert trace[0].role == "assistant"
        assert trace[0].tool_calls is not None
        assert trace[0].message_kind == "assistant_tool_call"
        assert trace[0].iteration == 0
        assert trace[0].finish_reason == "tool_calls"
        assert trace[1].role == "tool"
        assert trace[1].tool_call_id == "tc1"
        assert trace[1].message_kind == "tool_result"
        assert trace[1].tool_name == "weather"
        assert trace[1].iteration == 0
        # Last message is the final assistant reply
        assert trace[-1].role == "assistant"
        assert "22C" in trace[-1].content
        assert trace[-1].message_kind == "assistant_text"
        assert trace[-1].stop_reason == StopReason.COMPLETED.value
        assert trace[-1].iteration == 1
        assert len({msg.turn_id for msg in trace}) == 1


# ---------------------------------------------------------------------------
# Multi-tool turn
# ---------------------------------------------------------------------------


class TestMultiToolTurn:

    @pytest.mark.anyio
    async def test_multi_tool_calls_in_single_iteration(self) -> None:
        tc1 = ToolCall(id="tc1", name="weather", arguments={"city": "A"})
        tc2 = ToolCall(id="tc2", name="weather", arguments={"city": "B"})
        llm = FakeLLMAdapter([
            ChatResponse(content="", tool_calls=[tc1, tc2], finish_reason="tool_calls"),
            ChatResponse(content="A is hot, B is cold.", tool_calls=None, finish_reason="stop"),
        ])
        facade = FakeCapabilityFacade({"weather": "result"})
        engine = TurnEngine(llm=llm, tools=[FakeTool()], capability_facade=facade)
        msgs = [Message(role="user", content="compare")]

        response = await engine.run(messages=msgs)

        trace = response.message_trace
        # assistant(tool_calls) + tool(tc1) + tool(tc2) + final_assistant
        tool_msgs = [m for m in trace if m.role == "tool"]
        assert len(tool_msgs) == 2


# ---------------------------------------------------------------------------
# Tool failure
# ---------------------------------------------------------------------------


class TestToolFailure:

    @pytest.mark.anyio
    async def test_tool_error_captured_in_trace(self) -> None:
        tc = ToolCall(id="tc1", name="broken", arguments={})
        llm = FakeLLMAdapter([
            ChatResponse(content="", tool_calls=[tc], finish_reason="tool_calls"),
            ChatResponse(content="Sorry, error.", tool_calls=None, finish_reason="stop"),
        ])

        class FailingFacade:
            async def resolve_and_execute(self, query: Any, arguments: dict, context: dict | None = None) -> str:
                raise RuntimeError("tool crashed")

        engine = TurnEngine(llm=llm, tools=[FakeTool(name="broken")], capability_facade=FailingFacade())
        msgs = [Message(role="user", content="do it")]

        response = await engine.run(messages=msgs)

        tool_msgs = [m for m in response.message_trace if m.role == "tool"]
        assert len(tool_msgs) == 1
        assert "Error:" in tool_msgs[0].content
        assert tool_msgs[0].error == "tool crashed"
        assert tool_msgs[0].tool_name == "broken"


# ---------------------------------------------------------------------------
# Repeated tool detection
# ---------------------------------------------------------------------------


class TestRepeatedTool:

    @pytest.mark.anyio
    async def test_repeated_tool_stops_early(self) -> None:
        tc = ToolCall(id="tc1", name="weather", arguments={"city": "X"})
        llm = FakeLLMAdapter([
            ChatResponse(content="", tool_calls=[tc], finish_reason="tool_calls"),
            ChatResponse(content="", tool_calls=[tc], finish_reason="tool_calls"),
        ])
        facade = FakeCapabilityFacade({"weather": "result"})
        engine = TurnEngine(llm=llm, tools=[FakeTool()], capability_facade=facade)
        msgs = [Message(role="user", content="loop")]

        response = await engine.run(messages=msgs)

        assert response.stop_reason == StopReason.REPEATED_TOOL
        assert response.message_trace[-1].stop_reason == StopReason.REPEATED_TOOL.value


# ---------------------------------------------------------------------------
# Max iterations
# ---------------------------------------------------------------------------


class TestMaxIterations:

    @pytest.mark.anyio
    async def test_max_iterations_reached(self) -> None:
        tc = ToolCall(id="tc1", name="weather", arguments={"city": "X"})
        # Each iteration returns different args to avoid repeated-tool guard
        responses = []
        for i in range(5):
            tc_i = ToolCall(id=f"tc{i}", name="weather", arguments={"city": f"city-{i}"})
            responses.append(ChatResponse(content="", tool_calls=[tc_i], finish_reason="tool_calls"))

        llm = FakeLLMAdapter(responses)
        facade = FakeCapabilityFacade({"weather": "result"})
        engine = TurnEngine(llm=llm, tools=[FakeTool()], max_iterations=3, capability_facade=facade)
        msgs = [Message(role="user", content="go")]

        response = await engine.run(messages=msgs)

        assert response.stop_reason == StopReason.MAX_TURNS


# ---------------------------------------------------------------------------
# Event emission
# ---------------------------------------------------------------------------


class TestEvents:

    @pytest.mark.anyio
    async def test_events_emitted_for_complete_turn(self) -> None:
        llm = FakeLLMAdapter([
            ChatResponse(content="done", tool_calls=None, finish_reason="stop"),
        ])
        engine = TurnEngine(llm=llm)
        events: list[AgentEvent] = []

        await engine.run(
            messages=[Message(role="user", content="hi")],
            on_event=events.append,
        )

        event_types = [e.type.value for e in events]
        assert "thinking" in event_types
        assert "complete" in event_types
