"""Hailo provider – direct HailoRT hardware inference via hailo_platform."""

from __future__ import annotations

import copy
import json
import re
from collections.abc import AsyncIterable
from typing import Any, Self
import asyncio

from mindbot.providers.base import Provider
from mindbot.providers.hailo.param import HailoProviderParam
from mindbot.context.models import (
    ProviderInfo,
    ChatResponse,
    FinishReason,
    Message,
    ToolCall,
    UsageInfo,
)
from mindbot.logging import logger


MODEL_HEF_MAP: dict[str, str] = {
    "qwen3:1.7b": "sha256_cc9b9d1c92e35249b5a9b7bc31fbd652f03bba1232e99b9a8271845ad6f17821",
    "qwen2.5-coder:1.5b": "sha256_773470cd8bd8157cb6c48c4c1871b2b1c85b4d4b4b68193486828f7e7681330d",
}

# KV cache capacity per model, determined at HEF compile time (kv_cache_size in pre_process_params).
MODEL_CONTEXT_WINDOW: dict[str, int] = {
    "qwen3:1.7b": 2048,
    "qwen2.5-coder:1.5b": 2048,
}


class _DeviceManager:
    """Hailo 设备单例管理器。

    - 同一进程内所有 HailoProvider 共享同一个 VDevice + LLM
    - 切换模型时自动释放旧设备、加载新模型
    - 引用计数：最后一个 provider 释放时才真正卸载设备
    """

    _instance: _DeviceManager | None = None

    def __init__(self) -> None:
        self._vdevice: Any = None
        self._llm: Any = None
        self._loaded_model: str | None = None
        self._ref_count: int = 0
        self._lock = asyncio.Lock()

    @classmethod
    def get(cls) -> _DeviceManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def acquire(self) -> None:
        self._ref_count += 1

    async def get_llm(self, hef_path: str, model: str) -> Any:
        async with self._lock:
            if self._llm is not None and self._loaded_model == model:
                return self._llm

            await self._release()

            def _load():
                from hailo_platform import VDevice
                from hailo_platform.genai import LLM
                vd = VDevice()
                llm = LLM(vd, hef_path)
                return vd, llm

            self._vdevice, self._llm = await asyncio.to_thread(_load)
            self._loaded_model = model
            logger.info("Hailo device loaded: {}", model)
            return self._llm

    async def release(self) -> None:
        self._ref_count = max(0, self._ref_count - 1)
        if self._ref_count == 0:
            async with self._lock:
                await self._release()

    async def _release(self) -> None:
        if self._llm is not None:
            await asyncio.to_thread(self._llm.release)
            self._llm = None
        if self._vdevice is not None:
            await asyncio.to_thread(self._vdevice.release)
            self._vdevice = None
        if self._loaded_model is not None:
            logger.info("Hailo device released: {}", self._loaded_model)
        self._loaded_model = None


def _parse_tool_calls(content: str) -> list[ToolCall]:
    """从模型输出中解析 tool call（兼容 Qwen3 和 Qwen2.5 格式）。"""
    calls: list[ToolCall] = []
    pattern = r'"name"\s*:\s*"([^"]+)"\s*,\s*"arguments"\s*:\s*(\{[^}]*\})'
    for name, args_str in re.findall(pattern, content):
        try:
            args = json.loads(args_str)
        except json.JSONDecodeError:
            args = {}
        calls.append(ToolCall(id="", name=name, arguments=args))
    return calls


class HailoProvider(Provider):
    """Direct Hailo hardware provider using hailo_platform SDK.

    Features:
    - Chat completions via Hailo NPU
    - Streaming token output
    - Tool calling (model-dependent)
    - Zero network overhead (direct hardware access)
    """

    def __init__(self, param: HailoProviderParam) -> None:
        self._param = param
        self._bound_tools: list[Any] | None = None
        self._device_mgr = _DeviceManager.get()
        self._device_mgr.acquire()

    def _get_hef_path(self, model: str | None = None) -> str:
        from pathlib import Path
        effective = model or self._param.model
        if effective not in MODEL_HEF_MAP:
            raise ValueError(
                f"未知模型: {effective}，可用模型: {list(MODEL_HEF_MAP.keys())}"
            )
        base = str(Path(self._param.hef_base_path).expanduser())
        return f"{base}/{MODEL_HEF_MAP[effective]}"

    def _build_gen_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if self._param.temperature > 0:
            kwargs["do_sample"] = True
            kwargs["temperature"] = self._param.temperature
        else:
            kwargs["do_sample"] = False
        if self._param.max_tokens and self._param.max_tokens > 0:
            kwargs["max_generated_tokens"] = self._param.max_tokens
        return kwargs

    async def aclose(self) -> None:
        await self._device_mgr.release()

    def _to_hailo_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for msg in messages:
            d: dict[str, Any] = {"role": msg.role}
            if isinstance(msg.content, str):
                d["content"] = msg.content
            else:
                texts = [part.text for part in msg.content if hasattr(part, "text")]
                d["content"] = " ".join(texts)
            result.append(d)
        return result

    # ------------------------------------------------------------------
    # Provider interface
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[Message],
        model: str | None = None,
        tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        effective_model = model or self._param.model
        hef_path = self._get_hef_path(effective_model)
        llm = await self._device_mgr.get_llm(hef_path, effective_model)
        hailo_msgs = self._to_hailo_messages(messages)

        effective_tools = tools if tools is not None else self._bound_tools

        gen_kwargs = self._build_gen_kwargs()

        def _generate():
            llm.clear_context()
            kw = dict(gen_kwargs)
            if effective_tools:
                kw["tools"] = [t.to_openai_format() for t in effective_tools]
            with llm.generate(hailo_msgs, **kw) as gen:
                return gen.read_all(600000)

        output = await asyncio.to_thread(_generate)

        # 清理特殊 token
        output = re.sub(r"<\|im_end\|>", "", output).strip()

        tool_calls = _parse_tool_calls(output)
        finish = FinishReason.TOOL_CALLS if tool_calls else FinishReason.STOP

        return ChatResponse(
            content=output,
            tool_calls=tool_calls if tool_calls else None,
            provider=self._make_info(model),
            finish_reason=finish,
            usage=UsageInfo(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        )

    async def chat_stream(
        self,
        messages: list[Message],
        model: str | None = None,
        tools: list[Any] | None = None,
        tool_calls_out: list[Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterable[str]:
        effective_tools = tools if tools is not None else self._bound_tools
        if effective_tools is not None:
            resp = await self.chat(messages, model=model, **kwargs)
            if resp.content:
                yield resp.content
            return

        effective_model = model or self._param.model
        hef_path = self._get_hef_path(effective_model)
        llm = await self._device_mgr.get_llm(hef_path, effective_model)
        hailo_msgs = self._to_hailo_messages(messages)
        gen_kwargs = self._build_gen_kwargs()

        def _token_iter():
            llm.clear_context()
            with llm.generate(hailo_msgs, **gen_kwargs) as gen:
                for token in gen:
                    if token != "<|im_end|>":
                        yield token

        queue: asyncio.Queue[str | None] = asyncio.Queue()

        def _producer():
            try:
                for token in _token_iter():
                    queue.put_nowait(token)
            finally:
                queue.put_nowait(None)

        asyncio.get_event_loop().run_in_executor(None, _producer)

        while True:
            token = await queue.get()
            if token is None:
                break
            yield token

    async def embed(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        raise NotImplementedError("HailoProvider does not support embeddings")

    def bind_tools(self, tools: list[Any]) -> Self:
        new = copy.copy(self)
        new._bound_tools = list(tools)
        return new  # type: ignore[return-value]

    def get_info(self) -> ProviderInfo:
        return self._make_info()

    def _make_info(self, model: str | None = None) -> ProviderInfo:
        effective_model = model or self._param.model

        # HEF context_window is determined at compile time (kv_cache_size)
        auto_detected = MODEL_CONTEXT_WINDOW.get(effective_model)

        # User override via param.context_window (but cannot exceed HEF limit)
        user_override = self._param.context_window

        # Determine final context_window:
        # - If user sets a value > HEF limit, clamp to HEF limit
        # - Otherwise use user override or auto-detected
        if user_override is not None and auto_detected is not None:
            if user_override > auto_detected:
                logger.warning(
                    "param.context_window=%d exceeds HEF limit=%d, clamped to %d",
                    user_override, auto_detected, auto_detected,
                )
                final_context_window = auto_detected
            else:
                final_context_window = user_override
        else:
            final_context_window = user_override if user_override is not None else auto_detected

        return ProviderInfo(
            provider="hailo",
            model=effective_model,
            supports_vision=False,
            supports_tools=True,
            context_window=final_context_window,
        )

    def get_model_list(self) -> list[str]:
        return list(MODEL_HEF_MAP.keys())
