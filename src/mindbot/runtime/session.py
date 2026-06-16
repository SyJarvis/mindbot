"""Runtime protocol bus for MindBot turns."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from mindbot.agent.models import AgentEvent, AgentResponse, EventType, RuntimeRequest, StopReason


class RuntimeOpType(str, Enum):
    USER_TURN = "user_turn"
    INTERRUPT = "interrupt"
    USER_INPUT_ANSWER = "user_input_answer"
    PENDING_USER_INPUT = "pending_user_input"


class RuntimeEventType(str, Enum):
    TURN_STARTED = "turn_started"
    AGENT_EVENT = "agent_event"
    TURN_COMPLETE = "turn_complete"
    ERROR = "error"


@dataclass
class RuntimeOp:
    type: RuntimeOpType
    message: str | None = None
    session_id: str = "default"
    tools: list[Any] | None = None
    request_id: str | None = None
    answer: str | None = None
    input_text: str | None = None

    @classmethod
    def user_turn(
        cls,
        message: str,
        *,
        session_id: str = "default",
        tools: list[Any] | None = None,
    ) -> "RuntimeOp":
        return cls(
            type=RuntimeOpType.USER_TURN,
            message=message,
            session_id=session_id,
            tools=tools,
        )

    @classmethod
    def user_input_answer(cls, request_id: str, answer: str) -> "RuntimeOp":
        return cls(type=RuntimeOpType.USER_INPUT_ANSWER, request_id=request_id, answer=answer)

    @classmethod
    def pending_user_input(cls, input_text: str) -> "RuntimeOp":
        return cls(type=RuntimeOpType.PENDING_USER_INPUT, input_text=input_text)

    @classmethod
    def interrupt(cls) -> "RuntimeOp":
        return cls(type=RuntimeOpType.INTERRUPT)


@dataclass
class RuntimeEvent:
    op_id: str
    type: RuntimeEventType
    data: dict[str, Any] = field(default_factory=dict)
    agent_event: AgentEvent | None = None
    response: AgentResponse | None = None


class RuntimeSession:
    """A lightweight Op/Event session wrapper around MindBot.chat()."""

    def __init__(self, bot: Any, *, maxsize: int = 256) -> None:
        self._bot = bot
        self._queue: asyncio.Queue[RuntimeEvent] = asyncio.Queue(maxsize=maxsize)
        self._turn_task: asyncio.Task[Any] | None = None
        self._pending_runtime_request: RuntimeRequest | None = None
        self._pending_runtime_answer: asyncio.Future[str] | None = None
        self._queued_user_inputs: list[str] = []

    async def submit(self, op: RuntimeOp) -> str:
        op_id = uuid.uuid4().hex
        if op.type == RuntimeOpType.USER_TURN:
            self._submit_user_turn(op_id, op)
        elif op.type == RuntimeOpType.USER_INPUT_ANSWER:
            self._submit_user_input_answer(op)
        elif op.type == RuntimeOpType.PENDING_USER_INPUT:
            self._submit_pending_user_input(op)
        elif op.type == RuntimeOpType.INTERRUPT:
            self._submit_interrupt()
        else:
            raise ValueError(f"Unsupported runtime op: {op.type}")
        return op_id

    async def next_event(self) -> RuntimeEvent:
        return await self._queue.get()

    def is_running(self) -> bool:
        return self._turn_task is not None and not self._turn_task.done()

    @property
    def current_task(self) -> asyncio.Task[Any] | None:
        return self._turn_task

    @property
    def pending_user_input_request_id(self) -> str | None:
        request = self.pending_runtime_request
        if request is None:
            return None
        return request.request_id

    @property
    def pending_runtime_request(self) -> RuntimeRequest | None:
        if self._pending_runtime_answer is None or self._pending_runtime_answer.done():
            return None
        return self._pending_runtime_request

    @property
    def queued_count(self) -> int:
        return len(self._queued_user_inputs)

    def drain_queued_user_inputs_now(self) -> list[str]:
        queued = self._queued_user_inputs
        self._queued_user_inputs = []
        return queued

    async def drain_events_until_complete(self) -> AgentResponse:
        while True:
            event = await self.next_event()
            if event.type == RuntimeEventType.TURN_COMPLETE and event.response is not None:
                return event.response
            if event.type == RuntimeEventType.ERROR:
                message = str(event.data.get("message", "Runtime error"))
                return AgentResponse(content=message, stop_reason=StopReason.ERROR)

    def _submit_user_turn(self, op_id: str, op: RuntimeOp) -> None:
        if self.is_running():
            if op.message:
                self._queued_user_inputs.append(op.message)
            return
        if op.message is None:
            raise ValueError("UserTurn requires message")
        self._turn_task = asyncio.create_task(self._run_user_turn(op_id, op))

    def _submit_user_input_answer(self, op: RuntimeOp) -> None:
        if self._pending_runtime_answer is None or self._pending_runtime_answer.done():
            return
        if self._pending_runtime_request is None:
            return
        if op.request_id != self._pending_runtime_request.request_id:
            return
        self._pending_runtime_answer.set_result(op.answer or "")
        self._pending_runtime_request = None
        self._pending_runtime_answer = None

    def _submit_pending_user_input(self, op: RuntimeOp) -> None:
        if op.input_text:
            self._queued_user_inputs.append(op.input_text)

    def _submit_interrupt(self) -> None:
        if self._turn_task is not None and not self._turn_task.done():
            self._turn_task.cancel()

    async def _run_user_turn(self, op_id: str, op: RuntimeOp) -> None:
        await self._send(RuntimeEvent(op_id=op_id, type=RuntimeEventType.TURN_STARTED))
        try:
            response = await self._bot.chat(
                op.message,
                session_id=op.session_id,
                tools=op.tools,
                on_event=lambda event: self._send_nowait(RuntimeEvent(
                    op_id=op_id,
                    type=RuntimeEventType.AGENT_EVENT,
                    agent_event=event,
                )),
                on_runtime_request=self._resolve_runtime_request,
                on_pending_user_input=self._drain_pending_user_input,
            )
            await self._send(RuntimeEvent(
                op_id=op_id,
                type=RuntimeEventType.TURN_COMPLETE,
                response=response,
                data={"content": response.content, "stop_reason": response.stop_reason.value},
            ))
        except asyncio.CancelledError:
            response = AgentResponse(content="", stop_reason=StopReason.USER_ABORTED)
            await self._send(RuntimeEvent(
                op_id=op_id,
                type=RuntimeEventType.TURN_COMPLETE,
                response=response,
                data={"content": "", "stop_reason": response.stop_reason.value},
            ))
        except Exception as exc:
            await self._send(RuntimeEvent(
                op_id=op_id,
                type=RuntimeEventType.ERROR,
                data={"message": str(exc)},
            ))
        finally:
            if self._pending_runtime_answer is not None and not self._pending_runtime_answer.done():
                self._pending_runtime_answer.cancel()
            self._pending_runtime_request = None
            self._pending_runtime_answer = None
            self._turn_task = None

    async def _resolve_runtime_request(self, request: RuntimeRequest) -> str:
        if self._pending_runtime_answer is not None and not self._pending_runtime_answer.done():
            self._pending_runtime_answer.cancel()
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        self._pending_runtime_request = request
        self._pending_runtime_answer = future
        try:
            return await future
        finally:
            if self._pending_runtime_answer is future:
                self._pending_runtime_request = None
                self._pending_runtime_answer = None

    async def _drain_pending_user_input(self) -> list[str]:
        return self.drain_queued_user_inputs_now()

    def _send_nowait(self, event: RuntimeEvent) -> None:
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self._queue.put_nowait(event)

    async def _send(self, event: RuntimeEvent) -> None:
        await self._queue.put(event)


RuntimeChatHandler = Callable[[str, str], Awaitable[AgentResponse]]


async def run_runtime_turn(
    bot: Any,
    message: str,
    *,
    session_id: str = "default",
    tools: list[Any] | None = None,
) -> AgentResponse:
    session = RuntimeSession(bot)
    await session.submit(RuntimeOp.user_turn(message, session_id=session_id, tools=tools))
    return await session.drain_events_until_complete()


async def stream_runtime_turn_text(
    bot: Any,
    message: str,
    *,
    session_id: str = "default",
    tools: list[Any] | None = None,
) -> AsyncIterator[str]:
    session = RuntimeSession(bot)
    await session.submit(RuntimeOp.user_turn(message, session_id=session_id, tools=tools))
    while True:
        event = await session.next_event()
        if event.type == RuntimeEventType.AGENT_EVENT and event.agent_event is not None:
            if event.agent_event.type == EventType.DELTA:
                content = event.agent_event.data.get("content", "")
                if content:
                    yield content
        elif event.type in (RuntimeEventType.TURN_COMPLETE, RuntimeEventType.ERROR):
            return
