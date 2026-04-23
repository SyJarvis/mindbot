# Provider 模块

Provider 模块是 MindBot L5 基础设施层的核心组件，负责对接各类 LLM/VLM 推理服务。

## 概述

Provider 提供统一的抽象接口，屏蔽不同后端（OpenAI、Ollama、Transformers 等）的实现差异，向上层提供一致的对话、嵌入、流式输出能力。

## 架构位置

```
L5 Infrastructure Adapters
└── providers/
    ├── base.py              # 抽象基类定义
    ├── adapter.py           # ProviderAdapter 统一包装器
    ├── factory.py           # ProviderFactory 注册中心
    ├── openai/              # OpenAI 兼容 API 实现
    ├── ollama/              # Ollama 本地模型实现
    └── transformers/        # HuggingFace Transformers 实现
```

## 支持的 Provider 类型

| Provider | 类型标识 | 适用场景 |
|----------|----------|----------|
| [OpenAI](./configuration.md#openai-兼容服务) | `openai` | OpenAI、DeepSeek、Moonshot 等兼容 OpenAI API 的服务 |
| [Ollama](./configuration.md#ollama-本地) | `ollama` | 本地部署的 Ollama 服务 |
| [Transformers](./configuration.md#transformers) | `transformers` | 直接使用 HuggingFace Transformers 本地推理 |

## 快速导航

- [配置指南](./configuration.md) - 学习如何配置已有 Provider
- [扩展指南](./extending.md) - 开发新的 Provider 适配器
- [API 参考](./reference.md) - Provider 基类和接口文档

## 核心概念

### Provider 与 Param

每个 Provider 包含两个核心类：

```python
# Param - 配置参数
@dataclass
class MyProviderParam(BaseProviderParam):
    model: str = "default-model"
    api_key: str | None = None

# Provider - 实现类
class MyProvider(Provider):
    def __init__(self, param: MyProviderParam) -> None: ...
```

### 统一接口

所有 Provider 必须实现以下接口：

| 方法 | 说明 |
|------|------|
| `chat()` | 非流式对话 completion |
| `chat_stream()` | 流式对话输出 |
| `embed()` | 文本嵌入向量计算 |
| `bind_tools()` | 绑定工具（返回新实例） |
| `get_info()` | 获取 Provider 元信息 |

### 注册机制

Provider 通过工厂模式注册：

```python
from mindbot.providers import ProviderFactory

ProviderFactory.register("my_provider", MyProvider, MyProviderParam)
```

注册后在配置中通过 `type: my_provider` 使用。

## 配置示例

```yaml
providers:
  my-llm:
    type: openai
    endpoints:
      - base_url: https://api.example.com/v1
        api_key: ${API_KEY}
        models:
          - id: gpt-4
            role: chat
            level: high
            vision: true
```

详见 [配置指南](./configuration.md)。
