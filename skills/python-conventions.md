# MindBot Python 编码规范

> 本文件从 AGENTS.md 拆分，提供 Python 编码规范的详细说明。

---

## 项目结构

```text
mindbot/
├── pyproject.toml          # 项目配置
├── src/mindbot/
│   ├── agent/              # L2: Agent、TurnEngine、InputBuilder
│   ├── capability/         # L4: 工具注册与执行
│   ├── channels/           # L1: CLI、HTTP、Feishu
│   ├── config/             # 配置加载与环境变量
│   ├── context/            # L3: 上下文管理与压缩
│   ├── generation/         # L4: 动态工具生成
│   ├── memory/             # L4: 双记忆系统
│   ├── providers/          # L5: LLM Provider 适配
│   ├── routing/            # L4: 动态路由
│   ├── skills/             # L4: 技能注册与选择
│   ├── tools/              # 内置工具
│   └── utils/              # 纯函数工具
├── tests/
│   ├── agent/              # Agent 层测试
│   ├── capability/         # 能力系统测试
│   ├── context/            # 上下文测试
│   ├── providers/          # Provider 测试
│   └── ...
└── docs/                   # 文档
```

---

## 命名与代码风格

| 类型 | 规范 | 示例 |
|------|------|------|
| 模块/包 | snake_case, 短小 | `tool_registry.py`, `capability/` |
| 类名 | PascalCase | `WebSearchTool`, `AgentOrchestrator` |
| 函数/变量 | snake_case | `get_user_by_id`, `max_retry_count` |
| 常量 | UPPER_SNAKE_CASE | `DEFAULT_TIMEOUT_SEC`, `LLM_PROVIDERS` |
| 私有成员 | 前缀单下划线 | `_internal_cache`, `_validate_input()` |
| 缩写 | 仅业界共识 | `LLM`, `API`, `URL`, `ID` |

---

## 工具链配置

**pyproject.toml 关键配置：**

```toml
[tool.ruff]
line-length = 100
select = ["E", "F", "I", "UP", "RUF"]

[tool.mypy]
python_version = "3.10"
strict = true
disallow_any_generics = false

[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = ["src"]
```

**命令：**

```bash
# Lint
ruff check .

# Type check
mypy src/

# Test
pytest tests/ -m 'not integration' -q
```

---

## 文档字符串规范（Google Style）

```python
async def execute_search(
    query: str,
    limit: int = 10,
    timeout_sec: float = 30.0
) -> SearchResults:
    """执行网络搜索并返回结构化结果.

    Args:
        query: 搜索关键词，不能为空
        limit: 返回结果数量，范围 1-100
        timeout_sec: 请求超时时间（秒）

    Returns:
        SearchResults: 包含结果列表和元数据

    Raises:
        SearchAPIError: 当上游 API 返回错误或超时时
        ValueError: 当参数校验失败时

    Example:
        >>> results = await execute_search("Python typing", limit=5)
        >>> print(results.items[0].title)
    """
```

---

## 依赖管理

| 场景 | 推荐方案 |
|------|----------|
| 安装依赖 | `pip install -e .` 或 `uv sync` |
| 可选依赖 | `pyproject.toml` extras |
| 锁定版本 | 提交 lock 文件 |

**核心依赖原则**：

- 核心依赖保持精简
- 优先选择类型提示完善的库（`pydantic`, `aiohttp`, `openai`）
- 异步生态统一：`asyncio` + `aiohttp`，避免混用同步库

**当前核心依赖**（来自 pyproject.toml）：

```
pydantic>=2.0
pydantic-settings>=2.0
loguru>=0.7
typer>=0.12
prompt-toolkit>=3.0
rich>=13.0
croniter>=1.4
aiohttp>=3.9
openai
watchfiles>=0.20
```

---

## 异常处理规范

```python
# 定义领域异常基类
class AgentError(Exception):
    """Agent 系统基础异常"""
    def __init__(self, message: str, context: dict | None = None):
        super().__init__(message)
        self.context = context or {}

# 具体异常继承
class ToolExecutionError(AgentError): ...
class LLMRateLimitError(AgentError): ...
class ConfigurationError(AgentError): ...

# 使用：捕获具体异常，向上抛领域异常
async def safe_execute(tool: Tool, input_: Any) -> Any:
    try:
        return await tool.execute(input_data)
    except aiohttp.ClientError as e:
        raise ToolExecutionError(
            f"工具 {tool.name} 执行超时",
            context={"input": input_data}
        ) from e
    except pydantic.ValidationError as e:
        raise ValueError(f"输入校验失败：{e}") from e
```

---

*Python 编码规范 | MindBot v0.3.1*
