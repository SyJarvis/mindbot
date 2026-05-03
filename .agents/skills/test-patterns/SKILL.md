---
name: test-patterns
description: MindBot 测试编写规范——async 测试模式、FakeLLM/AsyncMock、fixture 约定、目录结构映射
when_to_use: 编写测试、修改测试、添加测试覆盖
---

# 测试编写规范

## Pytest 配置

```toml
# pyproject.toml
[tool.pytest.ini_options]
asyncio_mode = "auto"           # async 测试无需 @pytest.mark.asyncio
asyncio_default_fixture_loop_scope = "function"
testpaths = ["tests"]
pythonpath = ["src"]
collect_ignore_glob = ["tests/benchmarking/*"]
```

## 目录结构

测试目录与源码一一对应：

```
tests/
├── agent/           → src/mindbot/agent/
├── providers/       → src/mindbot/providers/
├── capability/      → src/mindbot/capability/
├── channels/        → src/mindbot/channels/
├── context/         → src/mindbot/context/
├── memory/          → src/mindbot/memory/
├── skills/          → src/mindbot/skills/
├── tools/           → src/mindbot/tools/
├── config/          → src/mindbot/config/
└── ...
```

## 测试组织

使用类分组，方法名描述测试场景：

```python
class TestMyProviderChat:
    """Test MyProvider.chat method."""

    async def test_chat_simple_message(self, mock_client, sample_message):
        ...

    async def test_chat_with_tools(self, mock_client):
        ...

    async def test_chat_handles_error(self, mock_client_failing):
        ...
```

## 核心模式

### 1. FakeLLM（推荐用于 Agent/编排层测试）

```python
class FakeLLM:
    """最小 LLM 替身，返回固定回复。"""

    def __init__(self, reply: str = "ok") -> None:
        self._reply = reply
        self.chat_calls: list[list[Message]] = []

    async def chat(self, messages: list[Message], **kwargs) -> ChatResponse:
        self.chat_calls.append(messages)
        return ChatResponse(content=self._reply, finish_reason=FinishReason.STOP)

    async def chat_stream(self, messages: list[Message], **kwargs) -> AsyncIterator[str]:
        yield self._reply
```

### 2. AsyncMock（用于 Provider 层测试）

```python
from unittest.mock import AsyncMock, MagicMock, patch

@pytest.fixture
def mock_client():
    with patch("openai.AsyncOpenAI") as mock_class:
        client = MagicMock()

        # Mock 同步响应
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = "test response"
        mock_completion.choices[0].finish_reason = "stop"
        client.chat.completions.create = AsyncMock(return_value=mock_completion)

        # Mock 流式响应
        async def mock_stream():
            for chunk in ["Hello", ", world", "!"]:
                yield MagicMock(choices=[MagicMock(delta=MagicMock(content=chunk))])
        client.chat.completions.create.return_value = mock_stream()

        yield client
```

### 3. 异步迭代器测试

```python
async def test_stream_yields_chunks(self, provider, sample_message):
    chunks = []
    async for chunk in provider.chat_stream([sample_message]):
        chunks.append(chunk)
    assert chunks == ["Hello", ", world", "!"]
```

### 4. MockBackend（用于 Capability 层测试）

```python
class MockBackend:
    """内存实现的 ExtensionBackend 协议。"""

    def __init__(self, capabilities=None):
        self._capabilities = capabilities or {}
        self.execute_calls = []

    async def execute(self, query, arguments):
        self.execute_calls.append((query, arguments))
        return self._capabilities.get(query.name, ToolResult(content="mock result"))
```

## 关键 Fixture

| Fixture | 位置 | 用途 |
|---------|------|------|
| `mock_openai_client` | `tests/providers/conftest.py` | OpenAI API mock |
| `mock_httpx_client` | `tests/providers/conftest.py` | Ollama HTTP mock |
| `sample_text_message` | `tests/providers/conftest.py` | 简单文本消息 |
| `sample_conversation` | `tests/providers/conftest.py` | 多轮对话 |
| `mock_backend` | `tests/capability/conftest.py` | Capability mock |
| `memory_base_path` | `tests/memory/conftest.py` | 临时记忆目录 |

## 注意事项

- `asyncio_mode = "auto"` 意味着 `async def test_xxx` 自动被识别为异步测试
- Provider 测试用 `conftest.py` 中的 fixture mock 外部 API，不要发真实请求
- 使用 `tmp_path`（pytest 内置）创建临时目录，不要手动清理
- 测试隔离：function-scoped fixture 确保每个测试独立
