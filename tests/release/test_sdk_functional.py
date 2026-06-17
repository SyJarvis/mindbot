"""Real-provider functional tests for the public Python SDK."""

from __future__ import annotations

import base64
import os
import uuid

import pytest

from mindbot.agent.models import EventType, RuntimeRequestType, StopReason
from mindbot.capability.backends.tooling import tool


pytestmark = [pytest.mark.integration, pytest.mark.release]


def _token(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12].upper()}"


async def test_chat_returns_real_model_response_and_runtime_events(sdk_bot) -> None:
    events = []

    response = await sdk_bot.chat(
        "请用一句中文说明当前对话服务可以正常响应。",
        session_id=f"chat-{uuid.uuid4().hex}",
        on_event=events.append,
    )

    assert response.stop_reason == StopReason.COMPLETED
    assert response.content.strip()
    assert events
    assert events[-1].type == EventType.COMPLETE
    assert all(event.turn_id for event in events)
    assert [event.seq for event in events] == list(range(1, len(events) + 1))


async def test_chat_stream_returns_incremental_real_model_output(sdk_bot) -> None:
    chunks: list[str] = []

    async for chunk in sdk_bot.chat_stream(
        "请简短介绍流式响应。",
        session_id=f"stream-{uuid.uuid4().hex}",
    ):
        chunks.append(chunk)

    assert chunks
    assert "".join(chunks).strip()


async def test_multi_turn_session_preserves_real_conversation_context(sdk_bot) -> None:
    secret = _token("SESSION_SECRET")
    session_id = f"multi-turn-{uuid.uuid4().hex}"

    first = await sdk_bot.chat(
        f"记住会话验证码 {secret}。只回复 READY。",
        session_id=session_id,
    )
    second = await sdk_bot.chat(
        "只回复我上一条消息中的会话验证码。",
        session_id=session_id,
    )

    assert first.stop_reason == StopReason.COMPLETED
    assert second.stop_reason == StopReason.COMPLETED
    assert secret in second.content
    assert session_id in sdk_bot.list_sessions()
    assert sdk_bot.get_conversation_token_count(session_id) > 0


async def test_registered_tool_executes_through_real_model(sdk_bot) -> None:
    expected = _token("TOOL_RESULT")
    calls: list[tuple[str, int]] = []

    @tool(name="mindbot_release_probe")
    def release_probe(label: str, count: int) -> str:
        """Return the release verification value. Always call this tool."""
        calls.append((label, count))
        return f"{expected}:{label}:{count}"

    events = []
    response = await sdk_bot.chat(
        "必须调用 mindbot_release_probe，参数 label='sdk'、count=7。"
        "调用后只回复工具返回的完整内容。",
        session_id=f"tool-{uuid.uuid4().hex}",
        tools=[release_probe],
        on_event=events.append,
    )

    assert response.stop_reason == StopReason.COMPLETED
    assert calls == [("sdk", 7)]
    assert expected in response.content
    event_types = [event.type for event in events]
    assert EventType.TOOL_EXECUTING in event_types
    assert EventType.TOOL_RESULT in event_types
    assert event_types[-1] == EventType.COMPLETE


async def test_runtime_request_resolver_continues_real_tool_turn(sdk_config) -> None:
    from mindbot import MindBot

    sdk_config.agent.task_progress_policy = "ask"
    sdk_config.agent.task_progress_review_after = 1
    bot = MindBot(config=sdk_config)
    calls: list[str] = []
    requests = []
    events = []

    @tool(name="runtime_request_probe")
    def runtime_request_probe(value: str) -> str:
        """Call once with value='checked', then wait for progress confirmation."""
        calls.append(value)
        return "runtime request probe completed"

    async def resolve(request):
        requests.append(request)
        return "Continue and finish now. Do not call another tool."

    response = await bot.chat(
        "调用 runtime_request_probe，参数 value='checked'。"
        "工具执行后，根据用户的进度确认完成任务。",
        session_id=f"runtime-request-{uuid.uuid4().hex}",
        tools=[runtime_request_probe],
        on_runtime_request=resolve,
        on_event=events.append,
    )

    assert calls == ["checked"]
    assert len(requests) == 1
    assert requests[0].request_type == RuntimeRequestType.USER_INPUT
    assert requests[0].metadata["reason"] == "task_progress_review"
    assert response.stop_reason == StopReason.COMPLETED
    event_types = [event.type for event in events]
    assert EventType.USER_INPUT_REQUEST in event_types
    assert EventType.USER_INPUT_RECEIVED in event_types


async def test_context_clear_removes_previous_real_session_state(sdk_bot) -> None:
    secret = _token("CLEAR_SECRET")
    session_id = f"clear-{uuid.uuid4().hex}"

    await sdk_bot.chat(
        f"记住会话验证码 {secret}。只回复 READY。",
        session_id=session_id,
    )
    assert sdk_bot.get_conversation_token_count(session_id) > 0

    sdk_bot.clear_context(session_id)

    assert sdk_bot.get_conversation_token_count(session_id) == 0


async def test_memory_write_and_recall_through_public_sdk(sdk_bot) -> None:
    marker = _token("MEMORY_FACT")
    content = f"MindBot SDK release memory fact: {marker}"

    sdk_bot.add_to_memory(content, permanent=True)
    hits = await sdk_bot.search_memory(marker, top_k=3)

    assert hits
    assert any(marker in hit.shard.text for hit in hits)
    assert any(hit.shard.is_permanent for hit in hits)


async def test_multimodal_image_reaches_real_model(sdk_bot) -> None:
    if os.environ.get("MINDBOT_SDK_TEST_VISION") != "1":
        pytest.skip("Set MINDBOT_SDK_TEST_VISION=1 with a vision-capable endpoint")

    red_pixel_png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB"
        "9Y9Z4L8AAAAASUVORK5CYII="
    )

    response = await sdk_bot.chat(
        "请简短说明你收到了图片。",
        images=[red_pixel_png],
        session_id=f"multimodal-{uuid.uuid4().hex}",
    )

    assert response.stop_reason == StopReason.COMPLETED
    assert response.content.strip()


async def test_start_stop_lifecycle_with_real_sdk_configuration(sdk_bot) -> None:
    assert sdk_bot.is_running is False

    await sdk_bot.start()
    assert sdk_bot.is_running is True

    await sdk_bot.stop()
    assert sdk_bot.is_running is False


def test_model_and_provider_introspection_uses_real_configuration(sdk_bot) -> None:
    assert sdk_bot.model == sdk_bot.config.agent.model
    assert sdk_bot.provider == sdk_bot.model.split("/", 1)[0]
    assert sdk_bot.list_available_models() == [sdk_bot.model]

    info = sdk_bot.get_llm_info()
    assert info.provider == sdk_bot.provider
    assert info.model == sdk_bot.model
