---
title: Agent 系统
---

# Agent 系统

MindBot 的 Agent 系统采用两层架构：

- **MindAgent**（监督者）-- 管理主 Agent、子 Agent 注册表和会话日志
- **Agent**（执行者）-- 自包含的对话 Agent，负责会话管理、工具注册和上下文维护

```
MindAgent (Supervisor)
  ├── 主 Agent (Agent)     ← 处理所有用户对话
  ├── 子 Agent A (Agent)   ← 可注册的子任务 Agent
  └── 子 Agent B (Agent)   ← 支持动态注册
```

---

## MindAgent

**模块路径**：`mindbot.agent.core`

监督者 Agent，作为用户层面的主要入口。将实际对话委托给内部的主 Agent，同时提供子 Agent 管理和会话日志功能。

### 构造函数

```python
MindAgent(
    config: Config,
    capability_facade: CapabilityFacade | None = None,
) -> None
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `config` | `Config` | - | 根配置实例 |
| `capability_facade` | `CapabilityFacade \| None` | `None` | 可选的能力层门面（Phase 2+） |

### 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `config` | `Config` | 当前配置 |
| `llm` | `ProviderAdapter` | 主 Agent 使用的 LLM 适配器 |
| `memory` | `MemoryManager` | 主 Agent 的内存管理器 |
| `tool_registry` | `ToolRegistry` | 主 Agent 的工具注册表 |

---

### 对话接口

#### `chat()`

```python
async def chat(
    message: str,
    session_id: str = "default",
    on_event: Callable[[AgentEvent], None] | None = None,
    tools: list[Any] | None = None,
) -> AgentResponse
```

主要异步对话入口，委托给主 Agent 执行。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `message` | `str` | - | 用户消息 |
| `session_id` | `str` | `"default"` | 会话标识符 |
| `on_event` | `Callable[[AgentEvent], None] \| None` | `None` | 实时事件回调 |
| `tools` | `list[Any] \| None` | `None` | 当次调用工具覆盖 |

**返回**：[`AgentResponse`](models.md#agentresponse)

#### `chat_stream()`

```python
async def chat_stream(
    message: str,
    session_id: str = "default",
    tools: list[Any] | None = None,
) -> AsyncIterator[str]
```

流式对话入口，委托给主 Agent 执行。

**返回**：`AsyncIterator[str]`

---

### 子 Agent 管理

#### `register_child_agent()`

```python
def register_child_agent(self, agent: Agent) -> None
```

将 `agent` 注册为子 Agent，使用其 `name` 属性作为注册键。

#### `get_child_agent()`

```python
def get_child_agent(self, name: str) -> Agent | None
```

根据名称返回子 Agent，未找到则返回 `None`。

#### `list_child_agents()`

```python
def list_child_agents(self) -> list[Agent]
```

返回所有已注册的子 Agent 列表。

---

### 工具管理

#### `register_tool()`

```python
def register_tool(self, tool: Any) -> None
```

向主 Agent 注册工具。

#### `list_tools()`

```python
def list_tools(self) -> list[Any]
```

返回主 Agent 已注册的工具列表。

#### `refresh_capabilities()`

```python
def refresh_capabilities(self) -> None
```

刷新主 Agent 和所有子 Agent 的能力集。

#### `reload_tools()`

```python
async def reload_tools(self) -> int
```

重新加载持久化工具并刷新所有 Agent。返回加载的工具数量。

#### `get_tool_count()`

```python
def get_tool_count(self) -> int
```

返回当前可见的工具数量。

#### `has_tool()`

```python
def has_tool(self, tool_name: str) -> bool
```

判断主 Agent 是否暴露指定名称的工具。

---

### 内存接口

#### `add_to_memory()`

```python
def add_to_memory(self, content: str, permanent: bool = False) -> None
```

向主 Agent 内存中添加内容。`permanent=True` 时提升为长期记忆。

#### `search_memory()`

```python
def search_memory(self, query: str, top_k: int = 5) -> list[Any]
```

搜索主 Agent 的内存。

---

## Agent

**模块路径**：`mindbot.agent.agent`

自包含的对话 Agent，每个实例管理一个 LLM Provider、工具注册表和按会话划分的上下文（LRU 淘汰）。

### 构造函数

```python
Agent(
    name: str,
    llm: ProviderAdapter,
    tools: list[Tool] | None = None,
    system_prompt: str = "",
    context_config: ContextConfig | None = None,
    memory: MemoryManager | None = None,
    memory_top_k: int = 5,
    tool_persistence: ToolPersistence = "none",
    max_iterations: int = 20,
    max_sessions: int = 1000,
    capability_facade: CapabilityFacade | None = None,
    tool_backend: ToolBackend | None = None,
    dynamic_manager: DynamicToolManager | None = None,
    skill_registry: SkillRegistry | None = None,
    skills_config: SkillsConfig | None = None,
) -> None
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | `str` | - | Agent 名称，用于日志和子 Agent 注册 |
| `llm` | `ProviderAdapter` | - | LLM Provider 适配器 |
| `tools` | `list[Tool] \| None` | `None` | 初始工具列表 |
| `system_prompt` | `str` | `""` | 系统提示词 |
| `context_config` | `ContextConfig \| None` | `None` | 上下文窗口配置，默认使用 `ContextConfig()` |
| `memory` | `MemoryManager \| None` | `None` | 内存管理器 |
| `memory_top_k` | `int` | `5` | 每轮检索的记忆块数 |
| `tool_persistence` | `ToolPersistence` | `"none"` | 工具消息持久化策略：`"none"` / `"summary"` / `"full"` |
| `max_iterations` | `int` | `20` | 最大工具迭代次数 |
| `max_sessions` | `int` | `1000` | 最大并发会话数（LRU 淘汰） |
| `capability_facade` | `CapabilityFacade \| None` | `None` | 能力层门面 |
| `tool_backend` | `ToolBackend \| None` | `None` | 工具后端 |
| `dynamic_manager` | `DynamicToolManager \| None` | `None` | 动态工具管理器 |
| `skill_registry` | `SkillRegistry \| None` | `None` | 技能注册表 |
| `skills_config` | `SkillsConfig \| None` | `None` | 技能配置 |

---

### 对话接口

#### `chat()`

```python
async def chat(
    message: str,
    session_id: str = "default",
    on_event: Callable[[AgentEvent], None] | None = None,
    tools: list[Any] | None = None,
) -> AgentResponse
```

非流式对话，支持工具调用和内存集成。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `message` | `str` | - | 用户消息文本 |
| `session_id` | `str` | `"default"` | 会话标识符（首次使用时自动创建会话） |
| `on_event` | `Callable[[AgentEvent], None] \| None` | `None` | 实时事件回调 |
| `tools` | `list[Any] \| None` | `None` | 当次调用工具覆盖。提供时完全替代已注册的工具 |

**返回**：[`AgentResponse`](models.md#agentresponse)

#### `chat_stream()`

```python
async def chat_stream(
    message: str,
    session_id: str = "default",
    tools: list[Any] | None = None,
) -> AsyncIterator[str]
```

流式对话。无工具时逐 Token 输出；有工具时先完成整轮再一次性输出。

**返回**：`AsyncIterator[str]`

---

### 工具管理

#### `register_tool()`

```python
def register_tool(self, tool: Any) -> None
```

注册工具。支持多种工具对象格式，自动适配具有 `name`、`description`、`parameters`/`parameters_json_schema` 和 `handler`/`run`/`execute` 方法的对象。

#### `list_tools()`

```python
def list_tools(self) -> list[Any]
```

返回所有当前可见的工具列表。

#### `refresh_capabilities()`

```python
def refresh_capabilities(self) -> None
```

刷新能力支持的工具并使缓存的编排器失效。

#### `reload_tools()`

```python
async def reload_tools(self) -> int
```

重新加载持久化动态工具并刷新能力视图。返回加载的工具数量。

#### `get_tool_count()`

```python
def get_tool_count(self) -> int
```

返回当前可见工具数量。

#### `has_tool()`

```python
def has_tool(self, tool_name: str) -> bool
```

判断指定名称的工具是否对 LLM 可见。

---

### 会话管理

Agent 使用 **LRU（最近最少使用）** 缓存管理会话：

- 每个 `session_id` 对应一个独立的 `ContextManager` 和 `TurnEngine` 实例
- 会话数量超过 `max_sessions` 时，自动淘汰最久未使用的会话
- 工具注册变更时，自动重建受影响会话的 `TurnEngine`

#### `set_session_journal()`

```python
def set_session_journal(self, journal: SessionJournal | None) -> None
```

附加或分离共享会话日志。

---

## 使用示例

### 直接使用 MindAgent

```python
from mindbot.agent.core import MindAgent
from mindbot.config.schema import Config

config = Config()
agent = MindAgent(config)

response = await agent.chat("你好！", session_id="user-1")
print(response.content)
```

### 创建独立 Agent

```python
from mindbot.agent.agent import Agent
from mindbot.providers.adapter import ProviderAdapter

llm = ...  # 创建 ProviderAdapter
agent = Agent(
    name="code-reviewer",
    llm=llm,
    system_prompt="你是一个代码审查助手。",
    max_iterations=10,
)

response = await agent.chat(
    "请审查这段代码：...",
    session_id="review-1",
)
```

### 注册子 Agent

```python
from mindbot.agent.core import MindAgent

supervisor = MindAgent(config)

# 创建并注册子 Agent
from mindbot.agent.agent import Agent
research_agent = Agent(name="research", llm=llm, system_prompt="研究助手")
supervisor.register_child_agent(research_agent)

# 查看子 Agent
children = supervisor.list_child_agents()
```

### 注册自定义工具

```python
class MyTool:
    name = "my_tool"
    description = "一个自定义工具"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "查询内容"}
        },
        "required": ["query"],
    }

    def handler(self, query: str) -> str:
        return f"处理结果: {query}"

agent.register_tool(MyTool())

response = await agent.chat("使用 my_tool 查询信息")
```
