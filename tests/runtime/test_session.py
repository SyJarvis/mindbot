from __future__ import annotations

import asyncio
from typing import Any

import pytest

from mindbot.agent.models import AgentEvent, AgentResponse, RuntimeRequest, RuntimeRequestType
from mindbot.runtime import (
    RuntimeEventType,
    RuntimeOp,
    RuntimeSession,
    run_runtime_turn,
    stream_runtime_turn_text,
)


class FakeBot:
    def __init__(self, *, request_runtime_answer: bool = False) -> None:
        self.pending_inputs: list[str] = []
        self.release = asyncio.Event()
        self.request_runtime_answer = request_runtime_answer

    async def chat(
        self,
        message: str,
        session_id: str = "default",
        tools: list[Any] | None = None,
        on_event: Any = None,
        on_user_input_request: Any = None,
        on_runtime_request: Any = None,
        on_pending_user_input: Any = None,
    ) -> AgentResponse:
        if on_event is not None:
            on_event(AgentEvent.delta("hello"))
        if self.request_runtime_answer and on_runtime_request is not None:
            answer = await on_runtime_request(RuntimeRequest.user_input(
                request_id="req-1",
                prompt="Continue?",
            ))
            return AgentResponse(content=answer)
        await self.release.wait()
        if on_pending_user_input is not None:
            self.pending_inputs = await on_pending_user_input()
        return AgentResponse(content=f"{session_id}:{message}")


@pytest.mark.anyio
async def test_runtime_session_wraps_chat_events_and_completion() -> None:
    bot = FakeBot()
    session = RuntimeSession(bot)

    op_id = await session.submit(RuntimeOp.user_turn("hi", session_id="s1"))
    started = await session.next_event()
    agent_event = await session.next_event()
    bot.release.set()
    complete = await session.next_event()

    assert started.op_id == op_id
    assert started.type == RuntimeEventType.TURN_STARTED
    assert agent_event.type == RuntimeEventType.AGENT_EVENT
    assert agent_event.agent_event is not None
    assert agent_event.agent_event.data["content"] == "hello"
    assert complete.type == RuntimeEventType.TURN_COMPLETE
    assert complete.response is not None
    assert complete.response.content == "s1:hi"


@pytest.mark.anyio
async def test_runtime_session_drains_pending_input_into_running_turn() -> None:
    bot = FakeBot()
    session = RuntimeSession(bot)

    await session.submit(RuntimeOp.user_turn("hi"))
    await session.next_event()
    await session.next_event()

    await session.submit(RuntimeOp.pending_user_input("also check humidity"))
    bot.release.set()
    await session.next_event()

    assert bot.pending_inputs == ["also check humidity"]


@pytest.mark.anyio
async def test_runtime_session_resolves_runtime_request() -> None:
    bot = FakeBot(request_runtime_answer=True)
    session = RuntimeSession(bot)

    await session.submit(RuntimeOp.user_turn("hi"))
    await session.next_event()
    await session.next_event()

    request = session.pending_runtime_request
    assert request is not None
    assert request.request_id == "req-1"
    assert request.request_type == RuntimeRequestType.USER_INPUT

    await session.submit(RuntimeOp.user_input_answer("req-1", "continue"))
    complete = await session.next_event()

    assert session.pending_runtime_request is None
    assert complete.type == RuntimeEventType.TURN_COMPLETE
    assert complete.response is not None
    assert complete.response.content == "continue"


@pytest.mark.anyio
async def test_run_runtime_turn_returns_final_response() -> None:
    bot = FakeBot()
    task = asyncio.create_task(run_runtime_turn(bot, "hi", session_id="s1"))
    await asyncio.sleep(0)

    bot.release.set()
    response = await task

    assert response.content == "s1:hi"


@pytest.mark.anyio
async def test_stream_runtime_turn_text_yields_delta_events() -> None:
    bot = FakeBot()
    stream = stream_runtime_turn_text(bot, "hi")

    first_chunk = await asyncio.wait_for(anext(stream), timeout=0.2)
    bot.release.set()
    remaining = [chunk async for chunk in stream]

    assert [first_chunk, *remaining] == ["hello"]
