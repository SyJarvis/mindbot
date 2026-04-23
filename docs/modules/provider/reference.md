# Provider API 参考

本文档提供 Provider 模块的 API 参考。

## 基类

### `Provider` (ABC)

位置：`mindbot.providers.base.Provider`

所有 Provider 实现必须继承的抽象基类。

```python
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any, Self

class Provider(ABC):
    """Abstract base class for all LLM/VLM providers."""
```

#### 抽象方法

##### `chat`

```python
@abstractmethod
async def chat(
    self,
    messages: list[Message],
    model: str | None = None,
    tools: list[Tool] | None = None,
    **kwargs: Any,
) -> ChatResponse
```

执行非流式对话 completion。

**参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `messages` | `list[Message]` | 对话历史消息列表 |
| `model` | `str \| None` | 覆盖默认模型的模型 ID |
| `tools` | `list[Tool] \| None` | 工具定义列表 |
| `**kwargs` | `Any` | 额外参数 |

**返回：** `ChatResponse` - 对话响应

---

##### `chat_stream`

```python
@abstractmethod
async def chat_stream(
    self,
    messages: list[Message],
    model: str | None = None,
    **kwargs: Any,
) -> AsyncIterator[str]
```

执行流式对话，产生文本块。

**注意：** 当 Provider 绑定了工具时，实现应回退到 `chat()` 并产生完整文本作为单个块。

**参数：** 同 `chat()`

**返回：** `AsyncIterator[str]` - 文本块迭代器

---

##### `embed`

```python
@abstractmethod
async def embed(
    self,
    texts: list[str],
    **kwargs: Any,
) -> list[list[float]]
```

计算文本的嵌入向量。

**参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `texts` | `list[str]` | 要嵌入的文本列表 |
| `**kwargs` | `Any` | 额外参数（如 `model`） |

**返回：** `list[list[float]]` - 嵌入向量列表

---

##### `bind_tools`

```python
@abstractmethod
def bind_tools(self, tools: list[Tool]) -> Self
```

返回一个绑定工具的新 Provider 实例（不可变模式）。

**参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `tools` | `list[Tool]` | 要绑定的工具列表 |

**返回：** `Self` - 新的 Provider 实例

**注意：** 原实例保持不变。

---

##### `get_info`

```python
@abstractmethod
def get_info(self) -> ProviderInfo
```

返回 Provider 的元数据信息。

**返回：** `ProviderInfo` - Provider 元数据

---

#### 默认方法

##### `get_model_list`

```python
def get_model_list(self) -> list[str]
```

返回可用模型 ID 列表。默认返回空列表，子类应覆盖以实现运行时发现。

**返回：** `list[str]`

---

##### `supports_vision`

```python
def supports_vision(self, model: str) -> bool
```

检查模型是否支持视觉输入。默认返回 `False`。

**参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `model` | `str` | 模型 ID |

**返回：** `bool`

---

### `BaseProviderParam`

位置：`mindbot.providers.param.BaseProviderParam`

所有 Provider 参数类的基类。

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass
class BaseProviderParam:
    """Common parameters shared by all LLM providers."""

    model: str = ""
    temperature: float = 0.7
    max_tokens: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)
```

**属性：**

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `model` | `str` | `""` | 默认模型 ID |
| `temperature` | `float` | `0.7` | 采样温度 |
| `max_tokens` | `int \| None` | `None` | 最大生成 token 数 |
| `extra` | `dict[str, Any]` | `{}` | 额外参数 |

---

## ProviderFactory

位置：`mindbot.providers.factory.ProviderFactory`

Provider 注册工厂，用于创建 Provider 实例。

```python
class ProviderFactory:
    """Factory for creating provider instances by type."""
```

### 类方法

#### `register`

```python
@classmethod
def register(
    cls,
    name: str,
    provider_class: type[Provider],
    param_class: type[BaseProviderParam],
) -> None
```

注册新的 Provider 类型。

**参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `name` | `str` | Provider 类型标识（如 `"openai"`） |
| `provider_class` | `type[Provider]` | Provider 实现类 |
| `param_class` | `type[BaseProviderParam]` | Param dataclass |

**示例：**

```python
from mindbot.providers import ProviderFactory

ProviderFactory.register("my_provider", MyProvider, MyProviderParam)
```

---

#### `create`

```python
@classmethod
def create(cls, provider_type: str, params: dict[str, Any]) -> Provider
```

创建 Provider 实例。

**参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `provider_type` | `str` | 已注册的 Provider 类型名 |
| `params` | `dict[str, Any]` | Provider 参数字典 |

**返回：** `Provider` - Provider 实例

**示例：**

```python
provider = ProviderFactory.create("openai", {
    "model": "gpt-4",
    "api_key": "sk-...",
})
```

---

## ProviderAdapter

位置：`mindbot.providers.adapter.ProviderAdapter`

统一 Provider 包装器，提供标准化接口。

```python
class ProviderAdapter:
    """Thin wrapper that instantiates the correct Provider by type."""
```

### 初始化

```python
def __init__(self, provider_type: str, params: dict[str, Any]) -> None
```

**参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `provider_type` | `str` | Provider 类型 |
| `params` | `dict[str, Any]` | Provider 参数 |

### 方法

#### `chat`

```python
async def chat(
    self,
    messages: list[Message],
    model: str | None = None,
    tools: list[Tool] | None = None,
    **kwargs: Any,
) -> ChatResponse
```

代理到内部 Provider 的 `chat` 方法。

---

#### `chat_stream`

```python
async def chat_stream(
    self,
    messages: list[Message],
    model: str | None = None,
    **kwargs: Any,
) -> AsyncIterator[str]
```

代理到内部 Provider 的 `chat_stream` 方法。

---

#### `embed`

```python
async def embed(self, texts: list[str], **kwargs: Any) -> list[list[float]]
```

代理到内部 Provider 的 `embed` 方法。

---

#### `bind_tools`

```python
def bind_tools(self, tools: list[Tool]) -> ProviderAdapter
```

返回绑定工具的新 ProviderAdapter 实例。

---

#### `get_info`

```python
def get_info(self) -> ProviderInfo
```

代理到内部 Provider 的 `get_info` 方法。

---

#### `supports_vision`

```python
def supports_vision(self, model: str) -> bool
```

代理到内部 Provider 的 `supports_vision` 方法。

---

## 数据模型

### `ChatResponse`

位置：`mindbot.context.models.ChatResponse`

```python
@dataclass
class ChatResponse:
    content: str
    tool_calls: list[ToolCall] | None = None
    provider: ProviderInfo | None = None
    finish_reason: FinishReason = FinishReason.STOP
    usage: UsageInfo | None = None
    reasoning_content: str | None = None
```

**字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `content` | `str` | 响应内容 |
| `tool_calls` | `list[ToolCall] \| None` | 工具调用列表 |
| `provider` | `ProviderInfo \| None` | Provider 元信息 |
| `finish_reason` | `FinishReason` | 结束原因 |
| `usage` | `UsageInfo \| None` | Token 使用量 |
| `reasoning_content` | `str \| None` | 推理模型思考内容 |

---

### `ProviderInfo`

位置：`mindbot.context.models.ProviderInfo`

```python
@dataclass
class ProviderInfo:
    provider: str
    model: str
    supports_vision: bool = False
    supports_tools: bool = True
```

**字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `provider` | `str` | Provider 类型标识 |
| `model` | `str` | 模型 ID |
| `supports_vision` | `bool` | 是否支持视觉 |
| `supports_tools` | `bool` | 是否支持工具 |

---

### `Message`

位置：`mindbot.context.models.Message`

```python
@dataclass
class Message:
    role: str  # "system", "user", "assistant", "tool"
    content: str | list[TextPart | ImagePart]
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    # ... other fields
```

**角色：**

| 值 | 说明 |
|----|------|
| `"system"` | 系统提示词 |
| `"user"` | 用户输入 |
| `"assistant"` | 助手回复 |
| `"tool"` | 工具结果 |

---

### `ToolCall`

位置：`mindbot.context.models.ToolCall`

```python
@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
```

---

### `FinishReason` (Enum)

位置：`mindbot.context.models.FinishReason`

```python
class FinishReason(Enum):
    STOP = "stop"              # 正常结束
    LENGTH = "length"          # 达到长度限制
    TOOL_CALLS = "tool_calls"  # 触发了工具调用
```

---

### `UsageInfo`

位置：`mindbot.context.models.UsageInfo`

```python
@dataclass
class UsageInfo:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
```

---

### `TextPart` / `ImagePart`

位置：`mindbot.context.models`

```python
@dataclass
class TextPart:
    text: str

@dataclass
class ImagePart:
    data: str | bytes  # URL or raw bytes
    mime_type: str = "image/jpeg"
```

---

## 内置 Provider

### OpenAI Provider

**类型标识：** `"openai"`

**Param 类：** `OpenAIProviderParam`

**额外字段：**

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `api_key` | `str \| None` | `None` | API 密钥 |
| `base_url` | `str \| None` | `None` | API 基础 URL |
| `timeout` | `float` | `120.0` | 请求超时（秒） |
| `vision_enabled` | `bool` | `False` | 是否启用视觉 |

---

### Ollama Provider

**类型标识：** `"ollama"`

**Param 类：** `OllamaProviderParam`

**额外字段：**

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `base_url` | `str` | `"http://localhost:11434"` | Ollama 服务地址 |
| `api_key` | `str \| None` | `None` | 认证密钥（如需要） |
| `vision_enabled` | `bool` | `False` | 是否启用视觉 |
| `auto_pull` | `bool` | `False` | 自动拉取缺失模型 |
| `pull_method` | `str` | `"api"` | 拉取方式：`api`/`cli`/`auto` |
| `pull_timeout` | `int` | `600` | 拉取超时（秒） |
| `pull_background` | `bool` | `True` | 后台拉取 |
| `preferred_models` | `list[str]` | `[]` | 优先模型列表 |
| `pull_retries` | `int` | `3` | 重试次数 |
| `pull_backoff` | `float` | `2.0` | 退避基数（秒） |

---

### Transformers Provider

**类型标识：** `"transformers"`

**Param 类：** `TransformersProviderParam`

**状态：** Stub，暂未完整实现

---

## 工具类型

### `Tool`

位置：`mindbot.capability.backends.tooling.models.Tool`

```python
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]

    def to_openai_format(self) -> dict[str, Any]: ...
```

**方法：**

##### `to_openai_format`

将工具转换为 OpenAI 函数调用格式。

**返回：** `dict[str, Any]`

```json
{
    "type": "function",
    "function": {
        "name": "tool_name",
        "description": "Tool description",
        "parameters": {
            "type": "object",
            "properties": {...},
            "required": [...]
        }
    }
}
```
