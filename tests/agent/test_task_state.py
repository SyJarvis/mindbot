from __future__ import annotations

import json

import pytest

from mindbot.agent.models import AgentResponse, StopReason
from mindbot.agent.task_state import TaskState
from mindbot.session.types import SessionMessage


def test_task_state_renders_current_intent() -> None:
    state = TaskState()

    state.before_turn("实现 memory curator")
    rendered = state.render()

    assert "Current task state:" in rendered
    assert "实现 memory curator" in rendered
    assert "Current plan:" in rendered


def test_task_state_updates_completed_progress() -> None:
    state = TaskState()
    state.before_turn("实现 memory curator")

    state.after_turn(AgentResponse(content="已完成 MemoryCurator", stop_reason=StopReason.COMPLETED))

    assert state.needs_user_input is False
    assert state.completed_steps == ["已完成 MemoryCurator"]


def test_task_state_marks_user_input_needed_as_blocker() -> None:
    state = TaskState()
    state.before_turn("执行长任务")

    state.after_turn(AgentResponse(content="请确认是否继续", stop_reason=StopReason.USER_INPUT_NEEDED))

    assert state.needs_user_input is True
    assert state.blockers == ["请确认是否继续"]


def test_task_state_round_trips_dict() -> None:
    state = TaskState(goal="g", completed_steps=["done"], confidence=0.8)

    restored = TaskState.from_dict(state.to_dict())

    assert restored.goal == "g"
    assert restored.completed_steps == ["done"]
    assert restored.confidence == 0.8


@pytest.mark.anyio
async def test_agent_injects_task_state_into_intent_block() -> None:
    from collections.abc import AsyncIterator
    from typing import Any

    from mindbot.agent.agent import Agent
    from mindbot.config.schema import ContextConfig
    from mindbot.context.models import Message

    class RecordingLLM:
        def __init__(self) -> None:
            self.calls: list[list[Message]] = []

        async def chat_stream(
            self,
            messages: list[Message],
            tools: list[Any] | None = None,
            tool_calls_out: list[Any] | None = None,
            **kw: Any,
        ) -> AsyncIterator[str]:
            self.calls.append(list(messages))
            yield "done"

        def bind_tools(self, tools: list[Any]) -> "RecordingLLM":
            return self

        def get_info(self):
            return None

    llm = RecordingLLM()
    agent = Agent(
        name="test",
        llm=llm,
        context_config=ContextConfig(max_tokens=4000),
    )

    await agent.chat("实现 task state", session_id="s1")

    assert llm.calls
    prompt_text = "\n".join(msg.text for msg in llm.calls[0])
    assert "Current task state:" in prompt_text
    assert "实现 task state" in prompt_text

    ctx = agent._get_session_context("s1")
    conv = ctx.get_block("conversation").messages
    assert conv[-1].content == "done"
    task_state = agent._get_task_state("s1")
    assert task_state.goal == "实现 task state"
    assert task_state.completed_steps == ["done"]


@pytest.mark.anyio
async def test_agent_restores_task_state_from_journal(tmp_path) -> None:
    from collections.abc import AsyncIterator
    from typing import Any

    from mindbot.agent.agent import Agent
    from mindbot.config.schema import ContextConfig
    from mindbot.context.models import Message
    from mindbot.session.store import SessionJournal

    class RecordingLLM:
        def __init__(self) -> None:
            self.calls: list[list[Message]] = []

        async def chat_stream(
            self,
            messages: list[Message],
            tools: list[Any] | None = None,
            tool_calls_out: list[Any] | None = None,
            **kw: Any,
        ) -> AsyncIterator[str]:
            self.calls.append(list(messages))
            yield "next done"

        def bind_tools(self, tools: list[Any]) -> "RecordingLLM":
            return self

    journal = SessionJournal(tmp_path / "journal")
    persisted = TaskState(goal="修复 memory", completed_steps=["已添加 curator"])
    journal.append("s1", [
        SessionMessage(role="user", content="old question"),
        SessionMessage(role="assistant", content="old answer"),
        SessionMessage(
            role="system",
            content=json.dumps(persisted.to_dict(), ensure_ascii=False),
            message_kind="task_state",
            is_meta=True,
        ),
    ])

    llm = RecordingLLM()
    agent = Agent(name="test", llm=llm, context_config=ContextConfig(max_tokens=4000))
    agent.set_session_journal(journal)

    await agent.chat("继续", session_id="s1")

    ctx = agent._get_session_context("s1")
    assert all(not msg.is_meta for msg in ctx.get_block("conversation").messages)
    prompt_text = "\n".join(msg.text for msg in llm.calls[0])
    assert "修复 memory" in prompt_text
    assert "已添加 curator" in prompt_text


def test_clear_context_drops_cached_task_state() -> None:
    from mindbot.agent.agent import Agent

    agent = Agent(name="test", llm=object())
    state = agent._get_task_state("s1")
    state.goal = "旧任务"

    agent.clear_context("s1")

    assert agent._get_task_state("s1").goal == ""
