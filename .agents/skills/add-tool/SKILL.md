---
name: add-tool
description: MindBot 工具开发指南——Tool 模型定义、handler 编写、ToolBackend 注册与 CapabilityFacade 执行路径
when_to_use: 添加新工具、新增 tool、为 Agent 增加可执行能力
---

# 添加新工具

## 架构定位

工具属于 **L4 能力层**，通过 `CapabilityFacade` 统一调度。核心原则：**工具定义与 handler 实现分离**。

## 执行路径

```
TurnEngine 检测到 tool_call
  → CapabilityFacade.resolve_and_execute()
    → CapabilityExecutor 路由
      → ToolBackend 执行
        → 调用 handler 函数
  → 返回 ToolResult
  → 加入消息列表，下一轮 LLM 迭代
```

## Tool 模型

```python
from mindbot.capability.backends.tooling.models import Tool, ToolParameter

# 方式一：显式定义
tool = Tool(
    name="my_tool",
    description="工具描述，LLM 根据这个决定何时调用",
    parameters=[
        ToolParameter(name="query", type="string", required=True,
                      description="搜索查询"),
        ToolParameter(name="limit", type="integer", required=False, default=5),
    ],
    handler=my_handler,
)

# 方式二：使用 @tool 装饰器
from mindbot.capability.backends.tooling.models import tool

@tool()
def search(query: str, limit: int = 5) -> str:
    """搜索内容"""  # docstring 自动作为 description
    return f"results for {query}"
```

## Handler 编写规范

```python
def my_handler(query: str, limit: int = 5) -> str:
    """
    handler 规范：
    1. 参数类型使用 Python 原生类型（str, int, bool, float, list, dict）
    2. 必须返回 str（序列化复杂结果用 json.dumps）
    3. 不要使用 async（CapabilityExecutor 内部处理异步包装）
    4. 异常由上层捕获，handler 内不要吞异常
    """
    results = do_something(query, limit)
    return json.dumps(results, ensure_ascii=False)
```

## 参数 schema

对于复杂参数，可使用 JSON Schema 覆盖：

```python
tool = Tool(
    name="my_tool",
    description="...",
    parameters_schema_override={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索内容"},
            "filters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "date_range": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "required": ["query"],
    },
    handler=my_handler,
)
```

## 注册方式

### 方式一：Agent 注册（推荐）

```python
from mindbot.capability.backends.tooling.models import Tool

def create_my_tools(workspace: str) -> list[Tool]:
    """创建工具列表"""

    def read_file(path: str) -> str:
        full_path = os.path.join(workspace, path)
        with open(full_path) as f:
            return f.read()

    return [
        Tool(
            name="read_file",
            description="读取文件内容",
            parameters=[
                ToolParameter(name="path", type="string", required=True),
            ],
            handler=read_file,
        ),
    ]

# 在 builder 中注册
tools = create_my_tools(workspace)
agent.register_tools(tools)
```

### 方式二：ToolBackend 注册

```python
from mindbot.capability.backends.tool_backend import ToolBackend

backend = ToolBackend.from_tools(my_tool_list)
facade.add_backend(backend)
```

## 安全约束

- **路径安全**：文件工具有 `restrict_to_workspace` 配置，启用后仅允许在指定目录操作
- **权限控制**：通过 `ToolSecurityLevel` 控制（DENY / ALLOWLIST / FULL）
- **沙箱执行**：Shell 工具支持 `ShellExecutionPolicy`（CWD_GUARD / SANDBOXED）

## 检查清单

- [ ] handler 函数参数类型清晰，返回 str
- [ ] Tool 的 description 清晰描述功能（LLM 依赖它决定何时调用）
- [ ] 复杂参数使用 parameters_schema_override
- [ ] 通过 `register_tools()` 或 `ToolBackend` 注册
- [ ] 测试放在 `tests/tools/test_my_tool.py`
- [ ] 涉及文件操作时注意路径安全
