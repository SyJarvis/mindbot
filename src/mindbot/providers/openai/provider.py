"""OpenAI provider – supports chat, vision (VLM), function calling, streaming, and embeddings."""

from __future__ import annotations

import copy
import json
from collections.abc import AsyncIterator
from typing import Any, Self
import openai
from mindbot.providers.base import Provider
from mindbot.providers.openai.param import OpenAIProviderParam
from mindbot.context.models import (
    ProviderInfo,
    ChatResponse,
    FinishReason,
    ImagePart,
    Message,
    TextPart,
    ToolCall,
    UsageInfo,
)
from mindbot.utils import get_logger

logger = get_logger("providers.openai")

# Model name prefixes/patterns that support vision input.
_VISION_PREFIXES = ("gpt-4o", "gpt-4-turbo", "gpt-4-vision", "o1", "o3")

# Well-known OpenAI/compatible model context windows (in tokens)
# Source: https://platform.openai.com/docs/models
OPENAI_MODEL_CONTEXT_WINDOW: dict[str, int] = {
    # GPT-4o series (128K context)
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4o-2024-05-13": 128000,
    "gpt-4o-2024-08-06": 128000,
    "gpt-4o-2024-11-20": 128000,
    # GPT-4 Turbo (128K context)
    "gpt-4-turbo": 128000,
    "gpt-4-turbo-2024-04-09": 128000,
    "gpt-4-0125-preview": 128000,
    "gpt-4-1106-preview": 128000,
    # GPT-4 (8K/32K)
    "gpt-4": 8192,
    "gpt-4-32k": 32768,
    # GPT-3.5 Turbo (16K/4K)
    "gpt-3.5-turbo": 16385,
    "gpt-3.5-turbo-16k": 16385,
    # o1 series (200K input, limited output)
    "o1-preview": 128000,
    "o1-mini": 128000,
    "o1": 200000,
    # o3 series
    "o3-mini": 200000,
    # DeepSeek (via OpenAI-compatible API)
    "deepseek-chat": 64000,
    "deepseek-coder": 16000,
    "deepseek-reasoner": 64000,
    # Moonshot (via OpenAI-compatible API)
    "moonshot-v1-8k": 8192,
    "moonshot-v1-32k": 32768,
    "moonshot-v1-128k": 131072,
    # GLM (via OpenAI-compatible API)
    "glm-4": 131072,
    "glm-4-flash": 131072,
    "glm-4-plus": 131072,
    # Qwen (via OpenAI-compatible API)
    "qwen-turbo": 8192,
    "qwen-plus": 32768,
    "qwen-max": 32768,
    "qwen-max-longcontext": 131072,
}


class OpenAIProvider(Provider):
    """Concrete provider using the ``openai`` Python SDK."""

    def __init__(self, param: OpenAIProviderParam) -> None:
        self._param = param
        client_kwargs: dict[str, Any] = {"timeout": param.timeout}
        if param.api_key:
            client_kwargs["api_key"] = param.api_key
        if param.base_url:
            client_kwargs["base_url"] = param.base_url

        self._client = openai.AsyncOpenAI(**client_kwargs)
        self._bound_tools: list[Any] | None = None

    # ------------------------------------------------------------------
    # Internal: message format conversion
    # ------------------------------------------------------------------

    def _to_openai_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        """Convert internal ``Message`` list to the OpenAI API dict format."""
        result: list[dict[str, Any]] = []
        for msg in messages:
            d: dict[str, Any] = {"role": msg.role}

            if isinstance(msg.content, str):
                d["content"] = msg.content
            else:
                parts: list[dict[str, Any]] = []
                for part in msg.content:
                    if isinstance(part, TextPart):
                        parts.append({"type": "text", "text": part.text})
                    elif isinstance(part, ImagePart):
                        if isinstance(part.data, str) and (
                            part.data.startswith("http://") or part.data.startswith("https://")
                        ):
                            image_url = {"url": part.data}
                        else:
                            data_str = (
                                part.data
                                if isinstance(part.data, str)
                                else __import__("base64").b64encode(part.data).decode()
                            )
                            image_url = {"url": f"data:{part.mime_type};base64,{data_str}"}
                        parts.append({"type": "image_url", "image_url": image_url})
                d["content"] = parts

            if msg.tool_calls:
                d["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in msg.tool_calls
                ]
                # Reasoning/thinking models require reasoning_content when assistant has tool_calls.
                if msg.role == "assistant":
                    d["reasoning_content"] = getattr(msg, "reasoning_content", None) or ""

            if msg.role == "tool" and msg.tool_call_id:
                d["tool_call_id"] = msg.tool_call_id

            result.append(d)
        return result

    def _build_api_kwargs(
        self,
        model: str | None,
        tools: list[Any] | None,
        **overrides: Any,
    ) -> dict[str, Any]:
        """Build keyword args for the OpenAI API call."""
        effective_model = model or self._param.model
        kwargs: dict[str, Any] = {
            "model": effective_model,
            "temperature": self._param.temperature,
        }
        if self._param.max_tokens is not None:
            kwargs["max_tokens"] = self._param.max_tokens

        # Call-time tools take precedence over bound tools.
        effective_tools = tools if tools is not None else self._bound_tools
        if effective_tools:
            kwargs["tools"] = [self._format_tool(t) for t in effective_tools]

        kwargs.update(self._param.extra)
        kwargs.update(overrides)
        return kwargs

    @staticmethod
    def _format_tool(tool: Any) -> dict[str, Any]:
        return tool.to_openai_format()

    def _parse_response(self, response: Any, model: str | None = None) -> ChatResponse:
        choice = response.choices[0]
        message = choice.message

        tool_calls: list[ToolCall] | None = None
        if message.tool_calls:
            tool_calls = [
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments),
                )
                for tc in message.tool_calls
            ]

        fr_map = {
            "stop": FinishReason.STOP,
            "tool_calls": FinishReason.TOOL_CALLS,
            "length": FinishReason.LENGTH,
        }
        finish = fr_map.get(choice.finish_reason, FinishReason.STOP)

        usage: UsageInfo | None = None
        if response.usage:
            usage = UsageInfo(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
            )

        reasoning_content: str | None = getattr(message, "reasoning_content", None)
        return ChatResponse(
            content=message.content or "",
            tool_calls=tool_calls,
            reasoning_content=reasoning_content,
            provider=self._make_info(model),
            finish_reason=finish,
            usage=usage,
        )

    def _make_info(self, model: str | None = None) -> ProviderInfo:
        effective_model = model or self._param.model

        # Get context window from known models table
        model_lower = effective_model.lower()
        auto_detected = None
        for key, ctx in OPENAI_MODEL_CONTEXT_WINDOW.items():
            if model_lower.startswith(key.lower()) or key.lower() in model_lower:
                auto_detected = ctx
                break

        # User override via param.context_window
        user_override = self._param.context_window

        # Determine final context_window:
        # - If user sets a value > auto-detected limit, clamp and warn
        # - Otherwise use user override or auto-detected
        if user_override is not None and auto_detected is not None:
            if user_override > auto_detected:
                logger.warning(
                    "param.context_window=%d exceeds model limit=%d, clamped to %d",
                    user_override, auto_detected, auto_detected,
                )
                final_context_window = auto_detected
            else:
                final_context_window = user_override
        else:
            final_context_window = user_override if user_override is not None else auto_detected

        return ProviderInfo(
            provider="openai",
            model=effective_model,
            supports_vision=self.supports_vision(effective_model),
            supports_tools=True,
            context_window=final_context_window,
        )

    # ------------------------------------------------------------------
    # Provider implementation
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[Message],
        model: str | None = None,
        tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        api_messages = self._to_openai_messages(messages)
        api_kwargs = self._build_api_kwargs(model, tools, **kwargs)
        response = await self._client.chat.completions.create(
            messages=api_messages,  # type: ignore[arg-type]
            **api_kwargs,
        )
        return self._parse_response(response, model)

    async def chat_stream(
        self,
        messages: list[Message],
        model: str | None = None,
        tools: list[Any] | None = None,
        tool_calls_out: list[Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """流式对话，同时支持工具调用。

        通过 tool_calls_out 可变列表返回解析后的 tool_calls，
        文本内容通过 yield 逐 token 返回。
        """
        # 兼容 bind_tools 模式：绑定工具但调用时未传 tools
        effective_tools = tools if tools is not None else self._bound_tools

        api_messages = self._to_openai_messages(messages)
        api_kwargs = self._build_api_kwargs(model, effective_tools, stream=True, **kwargs)
        stream = await self._client.chat.completions.create(
            messages=api_messages,  # type: ignore[arg-type]
            **api_kwargs,
        )

        # 累积 tool_call deltas（按 index 分组）
        tc_accum: dict[int, dict[str, str]] = {}

        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if not delta:
                continue

            # 文本 token
            if delta.content:
                yield delta.content

            # tool_call deltas
            if delta.tool_calls and tool_calls_out is not None:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tc_accum:
                        tc_accum[idx] = {"id": "", "name": "", "arguments": ""}
                    if tc.id:
                        tc_accum[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tc_accum[idx]["name"] = tc.function.name
                        if tc.function.arguments:
                            tc_accum[idx]["arguments"] += tc.function.arguments

        # 流结束后，解析累积的 tool_calls
        if tool_calls_out is not None and tc_accum:
            for idx in sorted(tc_accum):
                data = tc_accum[idx]
                tool_calls_out.append(
                    ToolCall(
                        id=data["id"],
                        name=data["name"],
                        arguments=json.loads(data["arguments"]),
                    )
                )

    async def embed(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        model = kwargs.pop("model", self._param.model)
        response = await self._client.embeddings.create(
            model=model,
            input=texts,
            **kwargs,
        )
        return [item.embedding for item in response.data]

    def bind_tools(self, tools: list[Any]) -> Self:
        new = copy.copy(self)
        new._bound_tools = list(tools)
        return new  # type: ignore[return-value]

    def get_info(self) -> ProviderInfo:
        return self._make_info()

    def get_model_list(self) -> list[str]:
        return []

    def supports_vision(self, model: str) -> bool:
        m = model.lower()
        return any(m.startswith(prefix) for prefix in _VISION_PREFIXES) or self._param.vision_enabled
