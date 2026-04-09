"""OpenAI-compatible adapter for running ToolCall-15 against MindBot."""

from __future__ import annotations

import asyncio
import copy
import json
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiohttp import web

from mindbot.builders import create_llm
from mindbot.capability.backends.tooling.models import Tool
from mindbot.config.loader import load_config
from mindbot.context.models import ChatResponse, Message, ToolCall, UsageInfo
from mindbot.utils import get_logger

if TYPE_CHECKING:
    from mindbot.config.schema import Config


logger = get_logger("benchmarking.toolcall15")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 11435
_GENERATION_KEYS = (
    "temperature",
    "top_p",
    "top_k",
    "min_p",
    "repetition_penalty",
)


def default_config_path() -> Path:
    """Return the default MindBot settings path."""
    return Path.home() / ".mindbot" / "settings.json"


def load_adapter_config(config_path: str | Path | None = None) -> "Config":
    """Load the MindBot config used by the benchmark adapter."""
    path = Path(config_path).expanduser() if config_path else default_config_path()
    return load_config(path)


def _stringify_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text_parts.append(str(part.get("text", "")))
        return "".join(text_parts)
    return ""


def _parse_tool_arguments(raw_arguments: Any) -> dict[str, Any]:
    if isinstance(raw_arguments, dict):
        return raw_arguments
    if isinstance(raw_arguments, str):
        try:
            parsed = json.loads(raw_arguments)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _messages_from_openai_payload(payload_messages: list[dict[str, Any]]) -> list[Message]:
    messages: list[Message] = []
    for payload in payload_messages:
        role = payload.get("role", "user")
        message = Message(
            role=role,
            content=_stringify_content(payload.get("content", "")),
            reasoning_content=payload.get("reasoning_content") or payload.get("reasoning"),
            tool_call_id=payload.get("tool_call_id"),
        )
        raw_tool_calls = payload.get("tool_calls") or []
        if isinstance(raw_tool_calls, list) and raw_tool_calls:
            message.tool_calls = []
            for index, raw_call in enumerate(raw_tool_calls):
                function = raw_call.get("function", {}) if isinstance(raw_call, dict) else {}
                message.tool_calls.append(
                    ToolCall(
                        id=str(raw_call.get("id") or f"tool_call_{index + 1}"),
                        name=str(function.get("name") or "unknown_tool"),
                        arguments=_parse_tool_arguments(function.get("arguments")),
                    )
                )
        messages.append(message)
    return messages


def _tools_from_openai_payload(payload_tools: list[dict[str, Any]] | None) -> list[Tool]:
    if not payload_tools:
        return []

    tools: list[Tool] = []
    for raw_tool in payload_tools:
        function = raw_tool.get("function", {}) if isinstance(raw_tool, dict) else {}
        name = str(function.get("name") or "").strip()
        if not name:
            continue

        schema = function.get("parameters")
        if not isinstance(schema, dict):
            schema = {"type": "object", "properties": {}}

        tools.append(
            Tool(
                name=name,
                description=str(function.get("description") or ""),
                parameters_schema_override=schema,
            )
        )
    return tools


def _usage_to_payload(usage: UsageInfo | None) -> dict[str, int]:
    if usage is None:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    return {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
    }


def _chat_response_to_openai_payload(response: ChatResponse, model: str) -> dict[str, Any]:
    message: dict[str, Any] = {
        "role": "assistant",
        "content": response.content or "",
    }
    if response.reasoning_content:
        message["reasoning_content"] = response.reasoning_content
    if response.tool_calls:
        message["tool_calls"] = [
            {
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.name,
                    "arguments": json.dumps(tool_call.arguments, ensure_ascii=True),
                },
            }
            for tool_call in response.tool_calls
        ]

    finish_reason = response.finish_reason.value if hasattr(response.finish_reason, "value") else str(response.finish_reason)

    return {
        "id": f"chatcmpl-mindbot-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish_reason,
            }
        ],
        "usage": _usage_to_payload(response.usage),
    }


class ToolCall15BenchmarkAdapter:
    """Serve a minimal OpenAI-compatible API backed by MindBot providers."""

    def __init__(self, config: "Config", *, default_model: str | None = None) -> None:
        self._config = config
        self._default_model = default_model
        self.app = web.Application()
        self.app.router.add_get("/health", self.handle_health)
        self.app.router.add_get("/v1/models", self.handle_models)
        self.app.router.add_post("/v1/chat/completions", self.handle_chat_completions)

    def _resolve_model_ref(self, requested_model: str | None) -> str:
        model_ref = (requested_model or self._default_model or self._config.agent.model).strip()
        if not model_ref:
            raise web.HTTPBadRequest(text=json.dumps({"error": {"message": "model is required"}}), content_type="application/json")
        if "/" not in model_ref:
            raise web.HTTPBadRequest(
                text=json.dumps(
                    {
                        "error": {
                            "message": (
                                "model must be an instance/model reference, "
                                f'for example "{self._config.agent.model}".'
                            )
                        }
                    }
                ),
                content_type="application/json",
            )
        return model_ref

    def _build_llm(self, model_ref: str) -> Any:
        config = copy.deepcopy(self._config)
        config.routing.auto = False
        config.agent.model = model_ref
        return create_llm(config)

    async def handle_health(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "status": "ok",
                "default_model": self._default_model or self._config.agent.model,
            }
        )

    async def handle_models(self, request: web.Request) -> web.Response:
        model_ref = self._default_model or self._config.agent.model
        return web.json_response(
            {
                "object": "list",
                "data": [
                    {
                        "id": model_ref,
                        "object": "model",
                        "owned_by": "mindbot",
                    }
                ],
            }
        )

    async def handle_chat_completions(self, request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except Exception as exc:  # pragma: no cover - aiohttp request parsing
            raise web.HTTPBadRequest(
                text=json.dumps({"error": {"message": f"invalid JSON: {exc}"}}),
                content_type="application/json",
            ) from exc

        if payload.get("stream"):
            raise web.HTTPBadRequest(
                text=json.dumps({"error": {"message": "stream=true is not supported by the ToolCall-15 adapter"}}),
                content_type="application/json",
            )

        raw_messages = payload.get("messages")
        if not isinstance(raw_messages, list) or not raw_messages:
            raise web.HTTPBadRequest(
                text=json.dumps({"error": {"message": "messages must be a non-empty list"}}),
                content_type="application/json",
            )

        model_ref = self._resolve_model_ref(payload.get("model"))
        llm = self._build_llm(model_ref)
        messages = _messages_from_openai_payload(raw_messages)
        tools = _tools_from_openai_payload(payload.get("tools"))
        generation_kwargs = {
            key: payload[key]
            for key in _GENERATION_KEYS
            if key in payload and payload[key] is not None
        }

        response = await llm.chat(
            messages,
            tools=tools or None,
            **generation_kwargs,
        )
        return web.json_response(_chat_response_to_openai_payload(response, model_ref))


def create_toolcall15_adapter_app(
    *,
    config_path: str | Path | None = None,
    default_model: str | None = None,
) -> web.Application:
    """Create an aiohttp app for ToolCall-15 benchmarking."""
    config = load_adapter_config(config_path)
    adapter = ToolCall15BenchmarkAdapter(config, default_model=default_model)
    return adapter.app


async def serve_toolcall15_adapter(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    config_path: str | Path | None = None,
    default_model: str | None = None,
) -> None:
    """Serve the ToolCall-15 adapter until interrupted."""
    app = create_toolcall15_adapter_app(config_path=config_path, default_model=default_model)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=host, port=port)
    await site.start()

    logger.info("ToolCall-15 adapter listening on http://{}:{}", host, port)
    logger.info("OpenAI-compatible endpoint: http://{}:{}/v1/chat/completions", host, port)

    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
