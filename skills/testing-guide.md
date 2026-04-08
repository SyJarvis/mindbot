# MindBot 测试驱动开发指南

> 本文件从 AGENTS.md 拆分，提供测试规范和 Checklist。

---

## 测试框架

- **pytest** + **pytest-asyncio**
- 异步模式：`asyncio_mode = "auto"`（pyproject.toml 已配置）
- 测试文件名：`test_*.py` 或 `*_test.py`

---

## 测试结构

```text
tests/
├── agent/              # Agent 层测试
│   ├── test_turn_engine.py
│   ├── test_persistence.py
│   └── test_input_builder.py
├── capability/         # 能力系统测试
│   ├── test_registry.py
│   ├── test_executor.py
│   └── test_facade.py
├── context/            # 上下文测试
│   ├── test_manager.py
│   └── test_compression.py
├── providers/          # Provider 测试
│   ├── test_openai.py
│   └── test_ollama.py
├── tools/              # 工具测试
│   ├── test_file_ops.py
│   └── test_shell_ops.py
└── conftest.py         # 共享 fixture
```

---

## 核心规则

1. **先写测试，后写实现** — 用测试定义行为契约
2. **一个 test 函数只验证一个行为**
3. **修改代码前先更新/新增测试**
4. **测试失败时立即修复，不积累测试债务**
5. **外部依赖必须 mock 隔离**

---

## 示例

### 基础异步测试

```python
import pytest

@pytest.mark.asyncio
async def test_agent_chat_returns_response():
    agent = Agent(name="test", llm=mock_llm)
    response = await agent.chat("hello", session_id="test")
    assert isinstance(response, AgentResponse)
    assert response.stop_reason == StopReason.COMPLETED
```

### Mock 外部依赖

```python
from unittest.mock import AsyncMock, MagicMock

@pytest.fixture
def mock_llm():
    llm = MagicMock(spec=ProviderAdapter)
    llm.chat = AsyncMock(return_value=ChatResponse(
        content="test response",
        tool_calls=None,
    ))
    return llm

@pytest.mark.asyncio
async def test_turn_engine_no_tools(mock_llm):
    engine = TurnEngine(llm=mock_llm, tools=[])
    response = await engine.run(messages=[
        Message(role="user", content="hello")
    ])
    assert response.content == "test response"
    assert response.stop_reason == StopReason.COMPLETED
```

### 测试工具执行

```python
@pytest.mark.asyncio
async def test_tool_execution_through_facade():
    facade = CapabilityFacade()
    registry.register(MyTool, name="my_tool")

    result = await facade.resolve_and_execute(
        CapabilityQuery(name="my_tool", capability_type=CapabilityType.TOOL),
        arguments={"input": "test"},
    )
    assert result is not None
```

### 测试压缩策略

```python
def test_truncate_strategy_preserves_recent():
    messages = [
        Message(role="user", content="old message"),
        Message(role="assistant", content="old response"),
        Message(role="user", content="recent message"),
        Message(role="assistant", content="recent response"),
    ]
    strategy = TruncateStrategy()
    result = strategy.compress(messages, target_tokens=50)
    # 最近的保留
    assert result[-1].content == "recent response"
```

---

## 运行命令

```bash
# 运行所有非集成测试
pytest tests/ -m 'not integration' -q

# 运行特定模块测试
pytest tests/agent/test_turn_engine.py -v

# 带覆盖率
pytest tests/ --cov=src/mindbot --cov-report=term-missing

# 只运行异步测试
pytest tests/ -k "async" -v
```

---

## Checklist

### 代码质量

- [ ] `ruff check .` 无错误
- [ ] `mypy src/` 无错误
- [ ] 所有 public 函数/类包含 Google style docstring
- [ ] 类型提示完整，无 `Any` 滥用
- [ ] 无 `print()` / `pdb` 残留，使用 `loguru`

### 测试覆盖

- [ ] 新增功能包含单元测试
- [ ] 异步函数使用 `@pytest.mark.asyncio`
- [ ] 外部依赖使用 mock 隔离
- [ ] 测试覆盖正常路径 + 异常路径

### 可维护性

- [ ] 单文件 <= 400 行，复杂模块拆分子包
- [ ] 无循环导入
- [ ] 配置项集中管理（Pydantic Settings + 环境变量）
- [ ] 敏感信息通过 `SecretStr` + 环境变量注入

### 架构合规

- [ ] 改动不绕过 `Agent.chat()` 主链路
- [ ] 新增工具通过 `CapabilityFacade` 调度
- [ ] 持久化通过 `PersistenceWriter` 统一写入
- [ ] 层依赖方向正确（L1 → L2 → L3/L4 → L5）

---

*测试驱动开发指南 | MindBot v0.3.1*
