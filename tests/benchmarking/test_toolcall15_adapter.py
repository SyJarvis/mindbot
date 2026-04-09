from __future__ import annotations

from types import SimpleNamespace

from aiohttp import web

from mindbot.benchmarking.toolcall15_adapter import (
    ToolCall15BenchmarkAdapter,
    _chat_response_to_openai_payload,
    _messages_from_openai_payload,
    _tools_from_openai_payload,
)
from mindbot.context.models import ChatResponse, FinishReason, ToolCall, UsageInfo


def _fake_config(model: str = "local-ollama/qwen3") -> SimpleNamespace:
    return SimpleNamespace(
        agent=SimpleNamespace(model=model),
        routing=SimpleNamespace(auto=True),
    )


def test_messages_from_openai_payload_preserves_tool_calls_and_tool_results() -> None:
    messages = _messages_from_openai_payload(
        [
            {"role": "system", "content": "You are helpful."},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "calculator",
                            "arguments": '{"expression":"2+2"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": '{"result": 4}',
            },
        ]
    )

    assert [message.role for message in messages] == ["system", "assistant", "tool"]
    assert messages[1].tool_calls is not None
    assert messages[1].tool_calls[0].name == "calculator"
    assert messages[1].tool_calls[0].arguments == {"expression": "2+2"}
    assert messages[2].tool_call_id == "call_1"


def test_tools_from_openai_payload_builds_internal_tools() -> None:
    tools = _tools_from_openai_payload(
        [
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "Search the web",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                },
            }
        ]
    )

    assert len(tools) == 1
    assert tools[0].name == "web_search"
    assert tools[0].parameters_json_schema()["required"] == ["query"]


def test_chat_response_to_openai_payload_serializes_tool_calls_and_usage() -> None:
    payload = _chat_response_to_openai_payload(
        ChatResponse(
            content="",
            tool_calls=[ToolCall(id="call_1", name="web_search", arguments={"query": "mindbot"})],
            finish_reason=FinishReason.TOOL_CALLS,
            usage=UsageInfo(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        ),
        model="local-ollama/qwen3",
    )

    assert payload["model"] == "local-ollama/qwen3"
    assert payload["choices"][0]["finish_reason"] == "tool_calls"
    assert payload["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "web_search"
    assert payload["usage"]["total_tokens"] == 15


def test_resolve_model_ref_uses_request_or_default_model() -> None:
    adapter = ToolCall15BenchmarkAdapter(_fake_config(), default_model="moonshot/kimi-k2.5")

    assert adapter._resolve_model_ref("local-ollama/qwen3") == "local-ollama/qwen3"
    assert adapter._resolve_model_ref(None) == "moonshot/kimi-k2.5"


def test_resolve_model_ref_rejects_non_model_refs() -> None:
    adapter = ToolCall15BenchmarkAdapter(_fake_config())

    try:
        adapter._resolve_model_ref("qwen3")
    except web.HTTPBadRequest as exc:
        assert "instance/model" in exc.text
    else:  # pragma: no cover - defensive branch
        raise AssertionError("Expected HTTPBadRequest")
