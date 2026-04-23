"""Ollama provider – uses the Ollama REST API (OpenAI-compatible /v1 endpoint)."""

from __future__ import annotations

import copy
import json
from collections.abc import AsyncIterator
from typing import Any, Self, Optional
import asyncio
import subprocess

from mindbot.config.vision import VISION_PATTERNS
from mindbot.providers.base import Provider
from mindbot.providers.ollama.param import OllamaProviderParam
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

logger = get_logger("providers.ollama")

class OllamaProvider(Provider):
    """Concrete provider talking to a local Ollama instance via HTTP.

    Ollama exposes an OpenAI-compatible ``/v1/chat/completions`` endpoint, so
    we use a thin ``httpx`` layer rather than duplicating the OpenAI SDK.
    """

    def __init__(self, param: OllamaProviderParam) -> None:
        self._param = param
        self._base_url = param.base_url.rstrip("/")
        self._headers: dict[str, str] = {}
        if param.api_key:
            self._headers["Authorization"] = f"Bearer {param.api_key}"
        self._async_client: Any = None
        self._client_loop_id: int | None = None
        self._bound_tools: list[Any] | None = None

    def _get_client(self) -> Any:
        """Get or create httpx.AsyncClient, handling event loop changes."""
        import httpx

        current_loop = asyncio.get_running_loop()
        current_loop_id = id(current_loop)

        # 如果事件循环变化或 client 不存在或已关闭，重新创建
        if (
            self._async_client is None
            or self._async_client.is_closed
            or self._client_loop_id != current_loop_id
        ):
            self._async_client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=120.0,
                headers=self._headers or None,
            )
            self._client_loop_id = current_loop_id

        return self._async_client

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def aclose(self) -> None:
        """Close the httpx client if it exists."""
        if self._async_client is not None and not self._async_client.is_closed:
            await self._async_client.aclose()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _to_ollama_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for msg in messages:
            d: dict[str, Any] = {"role": msg.role}
            if isinstance(msg.content, str):
                d["content"] = msg.content
            else:
                parts_text: list[str] = []
                images: list[str] = []
                for part in msg.content:
                    if isinstance(part, TextPart):
                        parts_text.append(part.text)
                    elif isinstance(part, ImagePart):
                        if isinstance(part.data, bytes):
                            images.append(__import__("base64").b64encode(part.data).decode())
                        else:
                            images.append(part.data)
                d["content"] = " ".join(parts_text)
                if images:
                    d["images"] = images

            if msg.tool_calls:
                d["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in msg.tool_calls
                ]

            if msg.role == "tool" and msg.tool_call_id:
                d["tool_call_id"] = msg.tool_call_id

            result.append(d)
        return result

    def _build_body(
        self,
        messages: list[dict[str, Any]],
        model: str | None,
        tools: list[Any] | None,
        **overrides: Any,
    ) -> dict[str, Any]:
        effective_model = model or self._param.model
        body: dict[str, Any] = {
            "model": effective_model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": self._param.temperature},
        }
        if self._param.max_tokens is not None:
            body["options"]["num_predict"] = self._param.max_tokens

        effective_tools = tools if tools is not None else self._bound_tools
        if effective_tools:
            body["tools"] = [t.to_openai_format() for t in effective_tools]

        body.update(overrides)
        return body

    def _parse_response(self, data: dict[str, Any], model: str | None = None) -> ChatResponse:
        msg = data.get("message", {})
        content = msg.get("content", "")

        tool_calls: list[ToolCall] | None = None
        raw_tcs = msg.get("tool_calls")
        if raw_tcs:
            tool_calls = []
            for tc in raw_tcs:
                fn = tc.get("function", {})
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    args = json.loads(args)
                tool_calls.append(
                    ToolCall(
                        id=tc.get("id", ""),
                        name=fn.get("name", ""),
                        arguments=args,
                    )
                )

        finish = FinishReason.TOOL_CALLS if tool_calls else FinishReason.STOP

        usage: UsageInfo | None = None
        if "prompt_eval_count" in data:
            usage = UsageInfo(
                prompt_tokens=data.get("prompt_eval_count", 0),
                completion_tokens=data.get("eval_count", 0),
                total_tokens=data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
            )

        return ChatResponse(
            content=content,
            tool_calls=tool_calls,
            provider=self._make_info(model),
            finish_reason=finish,
            usage=usage,
        )

    def _make_info(self, model: str | None = None) -> ProviderInfo:
        effective_model = model or self._param.model
        return ProviderInfo(
            provider="ollama",
            model=effective_model,
            supports_vision=self.supports_vision(effective_model),
            supports_tools=True,
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
        ollama_msgs = self._to_ollama_messages(messages)
        body = self._build_body(ollama_msgs, model, tools, **kwargs)
        resp = await self._get_client().post("/api/chat", json=body)
        resp.raise_for_status()
        return self._parse_response(resp.json(), model)

    async def chat_stream(
        self,
        messages: list[Message],
        model: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        if self._bound_tools is not None:
            resp = await self.chat(messages, model=model, **kwargs)
            if resp.content:
                yield resp.content
            return

        ollama_msgs = self._to_ollama_messages(messages)
        body = self._build_body(ollama_msgs, model, None, stream=True)
        async with self._get_client().stream("POST", "/api/chat", json=body) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                data = json.loads(line)
                chunk = data.get("message", {}).get("content", "")
                if chunk:
                    yield chunk

    async def embed(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        model = kwargs.get("model", self._param.model)
        results: list[list[float]] = []
        for text in texts:
            resp = await self._get_client().post(
                "/api/embeddings", json={"model": model, "prompt": text}
            )
            resp.raise_for_status()
            results.append(resp.json().get("embedding", []))
        return results

    def bind_tools(self, tools: list[Any]) -> Self:
        new = copy.copy(self)
        new._bound_tools = list(tools)
        return new  # type: ignore[return-value]

    def get_info(self) -> ProviderInfo:
        return self._make_info()

    def get_model_list(self) -> list[str]:
        try:
            # Use a short-lived synchronous client to keep this method sync
            httpx = __import__("httpx")
            headers: dict[str, str] = {}
            if self._param.api_key:
                headers["Authorization"] = f"Bearer {self._param.api_key}"
            resp = httpx.get(
                f"{self._base_url}/api/tags", timeout=10.0, headers=headers or None
            )
            resp.raise_for_status()
            data = resp.json()
            models: list[str] = []
            for item in data.get("models", []):
                # prefer the 'model' field, fall back to 'name'
                m = item.get("model") or item.get("name")
                if m:
                    models.append(m)
            return models
        except Exception:
            logger.exception("Failed to fetch model list from Ollama")
            return []

    # ------------------------------------------------------------------
    # Model management: discovery and pull
    # ------------------------------------------------------------------

    async def list_local_models(self) -> list[str]:
        """Async listing of local models via /api/tags."""
        try:
            resp = await self._get_client().get("/api/tags")
            resp.raise_for_status()
            data = resp.json()
            models: list[str] = []
            for item in data.get("models", []):
                m = item.get("model") or item.get("name")
                if m:
                    models.append(m)
            return models
        except Exception:
            logger.exception("Failed to list local models via Ollama API")
            return []

    async def is_model_available(self, model: str) -> bool:
        """Return True if *model* is present in local Ollama models."""
        m_norm = (model or "").lower()
        models = await self.list_local_models()
        return any(m_norm == m.lower() for m in models)

    async def pull_model(self, model: str, *, method: Optional[str] = None, background: Optional[bool] = None) -> bool:
        """Trigger model download. Returns True if the pull was started (or completed when not background).

        - method: 'api'|'cli'|'auto' (defaults to param.pull_method)
        - background: if True, start background task and return True immediately
        """
        method = method or self._param.pull_method
        background = self._param.pull_background if background is None else background

        if method == "auto":
            method = "api"

        if method == "api":
            async def _pull_api():
                try:
                    async with self._get_client().stream("POST", "/api/pull", json={"model": model, "stream": True}) as resp:
                        resp.raise_for_status()
                        async for text in resp.aiter_text():
                            if not text:
                                continue
                            # log raw progress chunks; callers can poll list_local_models
                            logger.debug("pull progress: %s", text.strip())
                    return True
                except Exception:
                    logger.exception("API pull failed for model %s", model)
                    return False

            if background:
                asyncio.create_task(_pull_api())
                return True
            return await _pull_api()

        # fallback to CLI
        if method == "cli":
            def _cli_pull():
                try:
                    proc = subprocess.run(["ollama", "pull", model], capture_output=True, text=True, check=False)
                    if proc.returncode == 0:
                        logger.info("CLI pull succeeded: %s", proc.stdout)
                        return True
                    logger.error("CLI pull failed (%s): %s", proc.returncode, proc.stderr)
                    return False
                except FileNotFoundError:
                    logger.exception("'ollama' CLI not found when attempting model pull")
                    return False

            loop = asyncio.get_running_loop()
            if background:
                loop.run_in_executor(None, _cli_pull)
                return True
            return await loop.run_in_executor(None, _cli_pull)

        logger.error("Unknown pull method: %s", method)
        return False

    async def ensure_model(self, model: str, *, wait: bool = True, timeout: Optional[int] = None) -> bool:
        """Ensure *model* is available locally. If missing and auto_pull enabled, trigger pull.

        If *wait* is True, block until model appears or timeout. Returns True when model is available.
        """
        # quick check
        if await self.is_model_available(model):
            return True

        # determine whether to pull
        if not self._param.auto_pull:
            logger.debug("Model %s not present and auto_pull disabled", model)
            return False

        timeout = timeout if timeout is not None else self._param.pull_timeout
        # trigger pull (background or foreground per param)
        started = await self.pull_model(model, method=self._param.pull_method, background=self._param.pull_background)
        if not started:
            return False

        if not wait:
            return True

        # wait until model appears or timeout
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if await self.is_model_available(model):
                return True
            await asyncio.sleep(2)
        logger.error("Timed out waiting for model %s to become available", model)
        return False

    def supports_vision(self, model: str) -> bool:
        m = model.lower()
        return any(pattern in m for pattern in VISION_PATTERNS)
