# MindBot 测试指南

## 概览

MindBot 使用 **pytest** 作为测试框架，当前共有 **316 个测试用例**，覆盖项目的所有核心模块。

Benchmark 相关文档：

- [ToolCall-15 Benchmark](toolcall15.md) — 当前阶段主 benchmark 的定位、运行方式和扩展路线
- [ToolCall-15 Baseline Template](toolcall15-baseline-template.md) — 首轮基线记录模板
- [Real Tools Benchmark](real-tools.md) — 真实文件/Shell/HTTP 工具执行 benchmark

```
tests/
├── agent/            # 8 tests  — 核心代理（TurnEngine、调度器、输入构建、持久化）
├── generation/       # 7 tests  — 动态工具生成（执行器、验证器、注册表、生成器）
├── capability/       # 4 tests  — 能力系统（Facade、注册表、执行器、后端）
├── providers/        # 4 tests  — LLM 提供商（OpenAI、Ollama、适配器、工厂）
├── channels/         # 3 tests  — 通道（飞书、HTTP、管理器）
├── bot/              # 1 test   — 系统提示词加载
├── builders/         # 1 test   — Agent 构建器
├── bus/              # 1 test   — 消息总线
├── cli/              # 1 test   — 配置生成
├── context/          # 1 test   — 上下文管理
├── session/          # 1 test   — 会话存储
├── skills/           # 1 test   — 技能加载
└── tools/            # 1 test   — 内置工具
```

---

## 快速开始

### 1. 安装依赖

```bash
# 安装项目（可编辑模式）
pip install -e .

# 安装测试框架
pip install pytest pytest-asyncio pytest-cov
```

### 2. 运行测试

```bash
# 运行全部测试
pytest

# 详细输出
pytest -v

# 运行指定模块
pytest tests/agent/
pytest tests/capability/

# 运行单个测试文件
pytest tests/agent/test_turn_engine.py

# 运行指定测试函数
pytest tests/agent/test_turn_engine.py::TestTurnEngine::test_basic_turn

# 带覆盖率报告
pytest --cov=src/mindbot --cov-report=html
```

### 3. pytest 配置

配置定义在 `pyproject.toml`：

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"   # 异步测试自动处理，无需手动加 @pytest.mark.asyncio
pythonpath = ["src"]    # 确保 import mindbot 正常工作
```

---

## 测试约定

### 命名规范

| 项目 | 规范 | 示例 |
|------|------|------|
| 测试文件 | `test_<module>.py` | `test_turn_engine.py` |
| 测试类 | `Test<Feature>` | `TestOpenAIProviderChat` |
| 测试函数 | `test_<behavior>` | `test_chat_simple_message` |
| Fixtures | 描述性名称 | `mock_openai_client`, `sample_capability` |

### 类型注解

所有测试函数都使用类型注解，保持与源码一致的风格：

```python
def test_register_capability(self, sample_capability: Capability) -> None:
    ...

async def test_chat_simple_message(self, mock_openai_client: MagicMock) -> None:
    ...
```

---

## 核心测试模式

### 1. 异步测试

项目大量使用异步代码，`asyncio_mode = "auto"` 让你无需手动标记：

```python
# 直接写 async 函数即可，无需 @pytest.mark.asyncio
async def test_streaming_response(self, mock_openai_stream: AsyncMock) -> None:
    result = await provider.chat(messages, stream=True)
    assert result.content == "expected"
```

### 2. Mock Provider

Provider 测试通过 `unittest.mock` 模拟 LLM 客户端，避免真实 API 调用：

```python
@pytest.fixture
def mock_openai_client() -> Generator[MagicMock, None, None]:
    with patch("openai.AsyncOpenAI") as mock_class:
        client = MagicMock()
        mock_class.return_value = client

        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = "Test response"

        client.chat.completions.create = AsyncMock(return_value=mock_completion)
        yield client
```

### 3. Mock Backend

Capability 测试使用自定义 `MockBackend`，提供可控的、确定性的行为：

```python
class MockBackend:
    """内存后端，记录所有执行操作，支持配置失败模式。"""

    def __init__(self, capabilities, raise_on_execute=None):
        self._capabilities = capabilities
        self.executed: list[tuple[str, dict]] = []
        self.raise_on_execute = raise_on_execute

    async def execute(self, capability_id: str, arguments: dict) -> str:
        self.executed.append((capability_id, arguments))
        if self.raise_on_execute:
            raise self.raise_on_execute
        return "mock-result"
```

### 4. Fake 对象

Agent 测试使用轻量级 Fake 对象替代真实依赖：

```python
class FakeLLMAdapter:
    """返回预配置响应的 LLM 适配器。"""
    def __init__(self, responses: list[ChatResponse]):
        self._responses = list(responses)

    async def chat(self, messages, **kwargs):
        return self._responses.pop(0)

class FakeCapabilityFacade:
    """对任何工具调用返回固定字符串。"""
    async def resolve_and_execute(self, query):
        return "fake-result"
```

### 5. 异常测试

使用 `pytest.raises` 验证异常行为：

```python
def test_resolve_missing_capability_raises(self, facade: CapabilityFacade) -> None:
    with pytest.raises(CapabilityNotFoundError) as exc_info:
        facade.resolve(CapabilityQuery(capability_id="missing"))
    assert "missing" in str(exc_info.value)
```

### 6. 文件系统测试

使用 pytest 内置的 `tmp_path` fixture，避免污染真实文件系统：

```python
def test_read_file_uses_workspace_guard(self, tmp_path: Path) -> None:
    target = tmp_path / "note.txt"
    target.write_text("hello", encoding="utf-8")
    # 在 tmp_path 内操作，安全隔离
```

当测试覆盖路径白名单时，建议显式构造一个“允许根目录”和其子目录，验证允许根会递归覆盖整棵目录树。

### 7. 环境变量测试

使用 `monkeypatch` 安全地控制环境变量：

```python
async def test_web_search_missing_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    # 测试缺少 API key 时的行为
```

---

## Fixture 体系

### capability conftest (`tests/capability/conftest.py`)

| Fixture | 用途 |
|---------|------|
| `sample_capability` | 提供标准的 Capability 实例 |
| `another_capability` | 提供第二个 Capability（用于多能力测试） |
| `mock_backend` | 预注册了能力的 MockBackend |
| `mock_backend_failing` | 配置为执行时抛出异常的 MockBackend |

### providers conftest (`tests/providers/conftest.py`)

| Fixture | 用途 |
|---------|------|
| `sample_text_message` | 纯文本消息 |
| `sample_multimodal_message` | 多模态消息 |
| `sample_conversation` | 多轮对话消息列表 |
| `sample_tool_calls` | 工具调用列表 |
| `mock_openai_client` | 模拟 OpenAI 客户端 |
| `mock_openai_stream` | 模拟 OpenAI 流式响应 |
| `mock_httpx_client` | 模拟 Ollama HTTP 客户端 |
| `mock_httpx_stream` | 模拟 Ollama 流式响应 |
| `openai_param` | OpenAI 提供商参数 |
| `ollama_param` | Ollama 提供商参数 |

---

## 开发闭环工作流

### 新增功能

```
1. 编写测试（红色阶段）
   └─ 在对应 tests/ 子目录创建测试文件
   └─ 使用现有 fixture 或创建新的 fixture
   └─ 用 Mock/Fake 隔离外部依赖

2. 运行测试确认失败
   └─ pytest tests/<module>/test_<feature>.py -v

3. 实现功能（绿色阶段）
   └─ 在 src/mindbot/ 对应模块中实现

4. 运行测试确认通过
   └─ pytest tests/<module>/ -v

5. 运行全量测试确认无回归
   └─ pytest

6. 提交代码
```

### Bug 修复

```
1. 编写复现测试（红色阶段）
   └─ 确保测试能稳定复现 bug

2. 修复代码（绿色阶段）

3. 运行全量测试
   └─ pytest

4. 确认覆盖率未降低
   └─ pytest --cov=src/mindbot
```

### 新增模块 Checklist

当你需要新增一个模块时，按以下 Checklist 行事：

- [ ] 在 `tests/` 下创建对应的测试目录
- [ ] 编写 `conftest.py`（如果需要共享 fixture）
- [ ] 每个公共类/函数至少一个测试文件
- [ ] 覆盖正常路径、边界条件、错误处理三种场景
- [ ] 异步函数使用 `async def test_` 模式
- [ ] 不依赖外部服务（使用 Mock/Fake/monkeypatch）
- [ ] 运行 `pytest` 确认全部通过

---

## CI 集成建议

在 CI 环境中推荐使用以下命令：

```bash
# 运行全量测试并生成覆盖率报告
pytest --cov=src/mindbot --cov-report=xml --cov-report=term-missing -v

# 仅运行失败的测试（调试用）
pytest --lf -v

# 并行执行（需安装 pytest-xdist）
pytest -n auto
```

---

## 常见问题

### Q: 为什么 `import mindbot` 报错？

确保以可编辑模式安装了项目：`pip install -e .`。pytest 配置中的 `pythonpath = ["src"]` 会在测试时自动处理，但 IDE 可能需要额外配置。

### Q: 异步测试需要 `@pytest.mark.asyncio` 吗？

不需要。`asyncio_mode = "auto"` 会自动识别 `async def test_` 函数。

### Q: 如何 Mock 外部 API？

使用 `unittest.mock.patch` 替换第三方客户端，参考 `tests/providers/conftest.py` 中的 `mock_openai_client` fixture。

### Q: 测试中需要真实的 LLM API Key 吗？

不需要。所有涉及外部 API 的测试都通过 Mock 隔离，可以在无网络环境下运行。
