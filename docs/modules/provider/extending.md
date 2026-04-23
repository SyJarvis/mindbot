# 新增 Provider 开发指南

本文档介绍如何为 MindBot 添加新的 LLM Provider 支持。

## 概述

新增 Provider 涉及以下步骤：

1. 创建模块目录和文件
2. 实现 Param 类（配置参数）
3. 实现 Provider 类（核心逻辑）
4. 注册到 ProviderFactory
5. 添加单元测试
6. 更新文档

## 步骤详解

### 1. 创建模块结构

在 `src/mindbot/providers/` 下创建新模块目录：

```bash
mkdir -p src/mindbot/providers/{your_provider}
touch src/mindbot/providers/{your_provider}/__init__.py
touch src/mindbot/providers/{your_provider}/param.py
touch src/mindbot/providers/{your_provider}/provider.py
```

### 2. 实现 Param 类

创建 `param.py`，继承 `BaseProviderParam`：

```python
"""YourProvider parameters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mindbot.providers.param import BaseProviderParam


@dataclass
class YourProviderParam(BaseProviderParam):
    """Parameters specific to the YourProvider.

    Attributes:
        model: Default model ID to use
        api_key: API authentication key (if required)
        base_url: API endpoint base URL
        temperature: Sampling temperature (0.0 - 2.0)
        max_tokens: Maximum tokens to generate
        vision_enabled: Whether this provider supports vision models
        timeout: Request timeout in seconds
        extra: Additional provider-specific parameters
    """

    model: str = "default-model"
    api_key: str | None = None
    base_url: str = "https://api.example.com/v1"
    temperature: float = 0.7
    max_tokens: int | None = None
    vision_enabled: bool = False
    timeout: float = 120.0
    extra: dict[str, Any] = field(default_factory=dict)
```

**关键字段说明：**

| 字段 | 说明 |
|------|------|
| `model` | 默认模型 ID |
| `vision_enabled` | 必须包含，用于多模态判断 |
| `extra` | 用于传递 provider 特有参数 |

### 3. 实现 Provider 类

创建 `provider.py`，继承 `Provider` 基类：

```python
"""YourProvider implementation."""

from __future__ import annotations

import copy
import json
from collections.abc import AsyncIterator
from typing import Any, Self
import asyncio

import httpx  # 或其他 HTTP 客户端

from mindbot.providers.base import Provider
from mindbot.providers.your_provider.param import YourProviderParam
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

logger = get_logger("providers.your_provider")


class YourProvider(Provider):
    """Concrete provider for Your LLM Service.

    Features:
    - Chat completions
    - Streaming output
    - Tool calling (if supported)
    - Vision input (if supported)
    - Embeddings (if supported)
    """

    def __init__(self, param: YourProviderParam) -> None:
        self._param = param
        self._base_url = param.base_url.rstrip("/")
        self._headers: dict[str, str] = {
            "Content-Type": "application/json",
        }
        if param.api_key:
            self._headers["Authorization"] = f"Bearer {param.api_key}"

        # HTTP 客户端管理（处理事件循环变化）
        self._async_client: httpx.AsyncClient | None = None
        self._client_loop_id: int | None = None

        self._bound_tools: list[Any] | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create httpx.AsyncClient, handling event loop changes.

        This method ensures the client is always bound to the current event loop,
        preventing "Event loop is closed" errors when loops change.
        """
        current_loop = asyncio.get_running_loop()
        current_loop_id = id(current_loop)

        if (
            self._async_client is None
            or self._async_client.is_closed
            or self._client_loop_id != current_loop_id
        ):
            self._async_client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._param.timeout,
                headers=self._headers,
            )
            self._client_loop_id = current_loop_id

        return self._async_client

    async def aclose(self) -> None:
        """Close the HTTP client."""
        if self._async_client is not None and not self._async_client.is_closed:
            await self._async_client.aclose()

    # ------------------------------------------------------------------
    # Message conversion
    # ------------------------------------------------------------------

    def _to_api_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        """Convert internal Message list to API format."""
        result: list[dict[str, Any]] = []
        for msg in messages:
            d: dict[str, Any] = {"role": msg.role}

            if isinstance(msg.content, str):
                d["content"] = msg.content
            else:
                # Multimodal content handling
                parts: list[dict[str, Any]] = []
                for part in msg.content:
                    if isinstance(part, TextPart):
                        parts.append({"type": "text", "text": part.text})
                    elif isinstance(part, ImagePart):
                        # Convert image to base64 if needed
                        if isinstance(part.data, str) and part.data.startswith("http"):
                            image_url = part.data
                        else:
                            data_str = (
                                part.data
                                if isinstance(part.data, str)
                                else __import__("base64").b64encode(part.data).decode()
                            )
                            image_url = f"data:{part.mime_type};base64,{data_str}"
                        parts.append({"type": "image_url", "image_url": {"url": image_url}})
                d["content"] = parts

            if msg.tool_calls:
                d["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                    }
                    for tc in msg.tool_calls
                ]

            if msg.role == "tool" and msg.tool_call_id:
                d["tool_call_id"] = msg.tool_call_id
                d["content"] = msg.content if isinstance(msg.content, str) else ""

            result.append(d)
        return result

    # ------------------------------------------------------------------
    # Provider interface implementation
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[Message],
        model: str | None = None,
        tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        """Execute a chat completion request."""
        api_messages = self._to_api_messages(messages)

        body: dict[str, Any] = {
            "model": model or self._param.model,
            "messages": api_messages,
            "temperature": self._param.temperature,
        }

        if self._param.max_tokens is not None:
            body["max_tokens"] = self._param.max_tokens

        # Add tools if provided
        effective_tools = tools if tools is not None else self._bound_tools
        if effective_tools:
            body["tools"] = [t.to_openai_format() for t in effective_tools]

        # Merge extra params
        body.update(self._param.extra)
        body.update(kwargs)

        # Make request
        response = await self._get_client().post(
            "/chat/completions",
            json=body,
        )
        response.raise_for_status()
        data = response.json()

        # Parse response
        choice = data["choices"][0]
        message = choice["message"]

        # Extract tool calls
        tool_calls: list[ToolCall] | None = None
        raw_tool_calls = message.get("tool_calls")
        if raw_tool_calls:
            tool_calls = []
            for tc in raw_tool_calls:
                fn = tc.get("function", {})
                args = fn.get("arguments", "{}")
                if isinstance(args, str):
                    args = json.loads(args)
                tool_calls.append(
                    ToolCall(
                        id=tc.get("id", ""),
                        name=fn.get("name", ""),
                        arguments=args,
                    )
                )

        # Determine finish reason
        finish_reason = choice.get("finish_reason", "stop")
        if finish_reason == "tool_calls" or tool_calls:
            finish = FinishReason.TOOL_CALLS
        elif finish_reason == "length":
            finish = FinishReason.LENGTH
        else:
            finish = FinishReason.STOP

        # Extract usage
        usage_data = data.get("usage", {})
        usage = UsageInfo(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
        )

        return ChatResponse(
            content=message.get("content", ""),
            tool_calls=tool_calls,
            provider=self._make_info(model),
            finish_reason=finish,
            usage=usage,
        )

    async def chat_stream(
        self,
        messages: list[Message],
        model: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Execute a streaming chat completion."""
        # If tools are bound, fall back to non-streaming
        if self._bound_tools is not None:
            response = await self.chat(messages, model=model, **kwargs)
            if response.content:
                yield response.content
            return

        api_messages = self._to_api_messages(messages)

        body: dict[str, Any] = {
            "model": model or self._param.model,
            "messages": api_messages,
            "temperature": self._param.temperature,
            "stream": True,
        }

        if self._param.max_tokens is not None:
            body["max_tokens"] = self._param.max_tokens

        body.update(self._param.extra)
        body.update(kwargs)

        async with self._get_client().stream(
            "POST",
            "/chat/completions",
            json=body,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line or line.startswith(":"):
                    continue
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        delta = chunk["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except (json.JSONDecodeError, KeyError):
                        continue

    async def embed(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        """Compute embeddings for texts."""
        model = kwargs.get("model", self._param.model)

        response = await self._get_client().post(
            "/embeddings",
            json={
                "model": model,
                "input": texts,
            },
        )
        response.raise_for_status()
        data = response.json()

        embeddings = []
        for item in data.get("data", []):
            embeddings.append(item.get("embedding", []))

        return embeddings

    def bind_tools(self, tools: list[Any]) -> Self:
        """Return a new provider instance with tools bound."""
        new = copy.copy(self)
        new._bound_tools = list(tools)
        return new  # type: ignore[return-value]

    def get_info(self) -> ProviderInfo:
        """Return provider metadata."""
        return self._make_info()

    def _make_info(self, model: str | None = None) -> ProviderInfo:
        """Create ProviderInfo for this provider."""
        effective_model = model or self._param.model
        return ProviderInfo(
            provider="your_provider",
            model=effective_model,
            supports_vision=self.supports_vision(effective_model),
            supports_tools=True,  # Set to False if tool calling not supported
        )

    def supports_vision(self, model: str) -> bool:
        """Check if model supports vision input.

        Override with provider-specific logic or use vision patterns.
        """
        # Option 1: Use vision flag from param
        if self._param.vision_enabled:
            return True

        # Option 2: Check model name patterns
        vision_patterns = ("vision", "vl", "multimodal")
        return any(p in model.lower() for p in vision_patterns)

    def get_model_list(self) -> list[str]:
        """Return list of available models from the API."""
        try:
            import httpx
            response = httpx.get(
                f"{self._base_url}/models",
                headers=self._headers,
                timeout=10.0,
            )
            response.raise_for_status()
            data = response.json()
            return [m.get("id", "") for m in data.get("data", [])]
        except Exception:
            logger.exception("Failed to fetch model list")
            return []
```

### 4. 导出模块

创建 `__init__.py`：

```python
"""YourProvider module."""

from mindbot.providers.your_provider.provider import YourProvider
from mindbot.providers.your_provider.param import YourProviderParam

__all__ = ["YourProvider", "YourProviderParam"]
```

### 5. 注册 Provider

编辑 `src/mindbot/providers/__init__.py`，添加注册：

```python
from mindbot.providers.factory import ProviderFactory

# ... existing imports ...
from mindbot.providers.your_provider import YourProvider, YourProviderParam

# Register built-in providers
ProviderFactory.register("openai", OpenAIProvider, OpenAIProviderParam)
ProviderFactory.register("ollama", OllamaProvider, OllamaProviderParam)
ProviderFactory.register("transformers", TransformersProvider, TransformersProviderParam)
ProviderFactory.register("your_provider", YourProvider, YourProviderParam)  # <-- 新增
```

### 6. 添加单元测试

创建测试文件 `tests/providers/test_your_provider.py`：

```python
"""Tests for YourProvider."""

import pytest
from unittest.mock import AsyncMock, Mock, patch

from mindbot.providers.your_provider import YourProvider, YourProviderParam
from mindbot.context.models import Message, FinishReason


@pytest.fixture
def param():
    return YourProviderParam(
        model="test-model",
        api_key="test-key",
        base_url="https://api.example.com/v1",
    )


@pytest.fixture
def provider(param):
    return YourProvider(param)


class TestYourProviderParam:
    def test_default_values(self):
        param = YourProviderParam()
        assert param.model == "default-model"
        assert param.api_key is None
        assert param.base_url == "https://api.example.com/v1"
        assert param.temperature == 0.7
        assert param.vision_enabled is False

    def test_custom_values(self):
        param = YourProviderParam(
            model="custom-model",
            api_key="custom-key",
            temperature=0.5,
            vision_enabled=True,
        )
        assert param.model == "custom-model"
        assert param.api_key == "custom-key"
        assert param.temperature == 0.5
        assert param.vision_enabled is True


class TestYourProvider:
    @pytest.mark.asyncio
    async def test_chat_basic(self, provider):
        mock_response = Mock()
        mock_response.json.return_value = {
            "choices": [{
                "message": {"content": "Hello!"},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        }

        with patch.object(provider, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            messages = [Message(role="user", content="Hi")]
            response = await provider.chat(messages)

            assert response.content == "Hello!"
            assert response.finish_reason == FinishReason.STOP
            assert response.usage.prompt_tokens == 10

    def test_supports_vision(self, provider):
        # Test vision detection logic
        assert provider.supports_vision("gpt-4-vision") is True
        assert provider.supports_vision("text-model") is False

    def test_get_info(self, provider):
        info = provider.get_info()
        assert info.provider == "your_provider"
        assert info.model == "test-model"
```

### 7. 更新文档

在 `docs/modules/provider/index.md` 的支持列表中添加新 Provider。

## 实现类型参考

### HTTP API Provider（OpenAI 兼容）

参考：`providers/openai/`

- 使用 `openai.AsyncOpenAI` SDK
- SDK 内部处理事件循环

### HTTP API Provider（原生）

参考：`providers/ollama/`

- 使用 `httpx.AsyncClient`
- 需要手动处理事件循环变化（使用 `_client_loop_id` 模式）

### 本地模型 Provider

参考：`providers/transformers/`（stub）

- 使用 `asyncio.to_thread()` 包装同步推理
- 注意 GPU/CPU 资源管理

## 常见问题

### Event loop is closed

**原因**：`httpx.AsyncClient` 与创建它的事件循环绑定，当事件循环变化时（如测试之间），缓存的 client 会失败。

**解决**：使用 `_client_loop_id` 模式检测循环变化并重新创建 client。详见上面的 `_get_client()` 实现。

### 工具调用格式

不同 Provider 的工具调用格式可能不同。常见格式：

```python
# OpenAI 格式
{
    "id": "call_xxx",
    "type": "function",
    "function": {
        "name": "tool_name",
        "arguments": '{"key": "value"}'  # JSON string
    }
}
```

转换时注意 `arguments` 可能是字符串或对象。

### 流式输出中断

流式输出需要正确处理连接中断和特殊消息（如 `[DONE]`）。确保：

```python
async for line in response.aiter_lines():
    if line == "data: [DONE]":
        break
    # Parse SSE format
```

### 多模态内容处理

图像数据可能是：
- URL 字符串（`http://...`）
- Base64 字符串
- `bytes` 对象

统一转换为 base64 data URL 格式：

```python
f"data:{mime_type};base64,{base64_encoded_data}"
```
