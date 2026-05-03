---
name: add-provider
description: MindBot LLM Provider 开发指南——Provider 基类接口、Param 配置类、Factory 注册机制与完整代码模板
when_to_use: 添加新 Provider、接入新 LLM（如 Gemini、Claude、Mistral）、新增模型适配器
---

# 添加新 Provider

## 架构定位

Provider 属于 **L5 基础设施适配层**，职责是封装不同 LLM API 为统一接口。上层（L2 编排层）通过 `ProviderAdapter` 调用，不感知具体实现。

## 接口契约

继承 `Provider` 基类，实现 5 个抽象方法：

```python
# src/mindbot/providers/base.py
class Provider(ABC):
    @abstractmethod
    async def chat(self, messages: list[Message], model: str | None = None,
                   tools: list[Tool] | None = None, **kwargs) -> ChatResponse:
        """同步对话补全"""

    @abstractmethod
    async def chat_stream(self, messages: list[Message], model: str | None = None,
                         tools: list[Any] | None = None, **kwargs) -> AsyncIterator[str]:
        """流式对话补全，yield 文本片段"""

    @abstractmethod
    async def embed(self, texts: list[str], **kwargs) -> list[list[float]]:
        """计算文本嵌入向量"""

    @abstractmethod
    def bind_tools(self, tools: list[Tool]) -> Self:
        """返回绑定了工具的新 Provider 实例（不可变模式）"""

    @abstractmethod
    def get_info(self) -> ProviderInfo:
        """返回 Provider 元数据"""
```

## 关键数据类型

```python
# 输入
from mindbot.context.models import Message, Role

# 输出
from mindbot.context.models import ChatResponse, FinishReason

# 工具
from mindbot.capability.backends.tooling.models import Tool

# 元数据
from mindbot.providers.base import ProviderInfo
```

## 目录结构

```
src/mindbot/providers/my_provider/
├── __init__.py        # 导出 MyProvider, MyProviderParam
├── param.py           # 参数配置类
└── provider.py        # Provider 实现
```

## 完整模板

### param.py

```python
from dataclasses import dataclass
from mindbot.providers.param import BaseProviderParam

@dataclass
class MyProviderParam(BaseProviderParam):
    model: str = "my-model-v1"
    api_key: str = ""
    base_url: str = "https://api.example.com/v1"
```

### provider.py

```python
import copy
from typing import Any, AsyncIterator, Self

from mindbot.providers.base import Provider, ProviderInfo
from mindbot.context.models import ChatResponse, FinishReason, Message
from mindbot.capability.backends.tooling.models import Tool

class MyProvider(Provider):
    def __init__(self, param: "MyProviderParam") -> None:
        self._param = param
        self._bound_tools: list[Tool] = []

    async def chat(self, messages: list[Message], model: str | None = None,
                   tools: list[Tool] | None = None, **kwargs) -> ChatResponse:
        # 1. 将 Message 列表转换为 API 请求格式
        # 2. 调用 LLM API
        # 3. 解析响应，返回 ChatResponse
        return ChatResponse(
            content="response text",
            finish_reason=FinishReason.STOP,
        )

    async def chat_stream(self, messages: list[Message], model: str | None = None,
                         tools: list[Any] | None = None, **kwargs) -> AsyncIterator[str]:
        # 1. 将 Message 列表转换为 API 请求格式
        # 2. 调用 LLM streaming API
        # 3. yield 每个文本片段
        yield "response chunk"

    async def embed(self, texts: list[str], **kwargs) -> list[list[float]]:
        # 调用 embedding API
        return [[0.0] * 768 for _ in texts]

    def bind_tools(self, tools: list[Tool]) -> Self:
        new = copy.copy(self)
        new._bound_tools = list(tools)
        return new

    def get_info(self) -> ProviderInfo:
        return ProviderInfo(
            provider="my_provider",
            model=self._param.model,
        )
```

### __init__.py

```python
from mindbot.providers.my_provider.param import MyProviderParam
from mindbot.providers.my_provider.provider import MyProvider

__all__ = ["MyProvider", "MyProviderParam"]
```

## 注册

在 `src/mindbot/providers/__init__.py` 中注册到工厂：

```python
from mindbot.providers.factory import ProviderFactory
from mindbot.providers.my_provider import MyProvider, MyProviderParam

ProviderFactory.register("my_provider", MyProvider, MyProviderParam)
```

## 配置

在 `settings.json` 的 `endpoints` 中添加：

```json
{
  "endpoints": {
    "my_provider": {
      "provider": "my_provider",
      "api_key": "sk-xxx",
      "base_url": "https://api.example.com/v1",
      "models": {
        "my-model-v1": {
          "roles": ["chat", "tool"],
          "max_tokens": 4096
        }
      }
    }
  }
}
```

## 检查清单

- [ ] 创建 `providers/my_provider/` 目录，包含 param.py、provider.py、\_\_init\_\_.py
- [ ] Param 类继承 `BaseProviderParam`
- [ ] Provider 类实现 5 个抽象方法
- [ ] `bind_tools()` 使用 copy 模式（不可变）
- [ ] 在 `providers/__init__.py` 注册到 `ProviderFactory`
- [ ] 测试放在 `tests/providers/test_my_provider.py`
- [ ] Mock 外部 API 调用，测试放在 `tests/providers/conftest.py` 中
