# Agent 开发指南（Python 优先版）

> 📋 适用场景：基于 Python 3.10+ 的智能体（Agent）系统开发  
> 🎯 核心目标：构建可维护、可测试、可扩展的 Agent 应用  
> 🔧 技术栈建议：Pydantic v2 + FastAPI + pytest + httpx + structlog

---

## MindBot 项目规范

> 本节是 MindBot 项目的专属约束，优先级高于下方通用原则。

### 全局异步架构

**MindBot 是全异步系统**，从入口到底层 I/O 均使用 `asyncio`，禁止在主链路引入同步阻塞。

- 所有公开接口必须是 `async def`，无同步版本
- CLI 命令、测试等顶层调用方通过 `asyncio.run()` 进入事件循环
- 禁止在 `async` 函数中使用 `asyncio.run()`（会嵌套事件循环）
- CPU 密集或遗留同步库必须通过 `asyncio.to_thread()` 卸载

### Chat 接口原则

`MindBot` 与 `MindAgent` 只暴露两类主 chat 入口，不允许新增其他变体：

| 入口 | 返回类型 | 说明 |
|------|----------|------|
| `chat(message, session_id, tools, on_event)` | `AgentResponse` | 主异步入口，带工具、记忆、Tracer |
| `chat_stream(message, session_id, tools)` | `AsyncIterator[str]` | 主流式入口，无工具时逐 token，有工具时单 chunk |

**工具传递规则**：

- 工具通过 `tools` 参数按调用级别传递，不强依赖实例级注册
- `tools is not None` → 本轮完全使用传入列表，覆盖 `register_tool()` 已注册的工具
- `tools is None` → 回退到 `tool_registry.list_tools()`
- 同一 session 若 `tools` 签名变化，orchestrator 自动重建，保证 LLM 可见工具与执行器工具始终同源

**兼容层规则**：

- 旧方法（`chat_async`、`chat_stream_async`、`chat_with_tools_async`、`chat_with_agent_async`）保留一个版本周期并发出 `DeprecationWarning`，内部委托到新主入口
- 禁止新增同步 chat 方法（`def chat` 而非 `async def chat`）
- 禁止在主链路之外再创建独立的"带工具"或"带记忆"变体

```python
# ✅ 正确用法
response = await bot.chat("帮我查天气", tools=[get_weather])
print(response.content)

async for chunk in bot.chat_stream("讲个故事"):
    print(chunk, end="", flush=True)

# ❌ 禁止
response = bot.chat(...)                      # 同步调用
result = await bot.chat_with_agent_async(...) # 已废弃变体
```

### 主链路不可绕过规则

所有对话路径（CLI、HTTP Channel、MessageBus）必须经过 `MindAgent.chat()`，以保证：

1. 记忆写入（`memory.append_to_short_term`）
2. Tracer 日志（`tracer.on_turn_start / on_turn_end`）
3. Orchestrator 工具编排

禁止在 serve/channel 层直接调用 `_agent.chat_async()` 或裸 LLM 接口绕过主链路。

### 系统分层架构（ASCII）

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│                    MindBot Layered Architecture (Recommended)               │
├──────────────────────────────────────────────────────────────────────────────┤
│ L1 Interface / Transport                                                    │
│  - channels/*  cli/*  bus/*                                                 │
│  - Receive/dispatch messages; protocol adaptation                           │
├──────────────────────────────────────────────────────────────────────────────┤
│ L2 Application / Use-case Orchestration                                     │
│  - bot.py  agent/core.py  agent/orchestrator.py  agent/streaming.py         │
│  - Turn/session flow orchestration, approvals, interrupt, consistency       │
│                                                                              │
│  [L2 Sub-layer: Turn Assembly]                                              │
│   - Scheduler (agent/scheduler.py)  assemble() / commit()                    │
├──────────────────────────────────────────────────────────────────────────────┤
│ L3 Conversation Domain                                                      │
│  - context/manager.py  context/models.py  context/compression.py            │
│  - Context blocks, token budget, message model, compression policy          │
├──────────────────────────────────────────────────────────────────────────────┤
│ L4 Capability + Memory Domain                                               │
│  - capability/*  memory/*  routing/*  generation/*                          │
│  - Tool capability, memory retrieval, dynamic routing, tool generation      │
├──────────────────────────────────────────────────────────────────────────────┤
│ L5 Infrastructure Adapters                                                  │
│  - providers/*  memory/storage.py  memory/markdown.py                       │
│  - External API/DB/FS integration                                           │
└──────────────────────────────────────────────────────────────────────────────┘

Dependency: L1 -> L2 -> (L3, L4) -> L5
```

### 完整数据流图（ASCII）

```text
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         MindBot 单轮对话数据流                                   │
└─────────────────────────────────────────────────────────────────────────────────┘

  User Input (text)
         │
         ▼
  ┌──────────────┐     ┌──────────────┐
  │ Channels     │     │ MindBot      │
  │ CLI/HTTP/... │────▶│ .chat()      │
  └──────────────┘     └──────┬───────┘
                             │
                             ▼
  ┌──────────────────────────────────────────────────────────────────────────────┐
  │ MindAgent.chat(message, session_id, tools, on_event)                         │
  │   └─ _get_session_scheduler(session_id) → Scheduler                          │
  └──────────────────────────────────────────────────────────────────────────────┘
                             │
                             ▼
  ┌──────────────────────────────────────────────────────────────────────────────┐
  │ Scheduler.assemble(message)                                                   │
  │   ├─ MemoryManager.search(query) → populate memory block                     │
  │   ├─ set_user_input(message)                                                  │
  │   └─ concatenate blocks: system_identity → memory → conversation → user_input│
  └──────────────────────────────────────────────────────────────────────────────┘
                             │
                             ▼
  ┌──────────────────────────────────────────────────────────────────────────────┐
  │ list[Message]  (system + memory + conversation + user_input)                  │
  └──────────────────────────────────────────────────────────────────────────────┘
                             │
                             ▼
  ┌──────────────────────────────────────────────────────────────────────────────┐
  │ AgentOrchestrator.chat(messages, on_event, execution)                         │
  │   loop:                                                                       │
  │     ├─ StreamingExecutor.execute_stream(messages, tools) → LLM                │
  │     ├─ ChatResponse (content, tool_calls?)                                    │
  │     ├─ if tool_calls: ApprovalManager → ToolExecutor.execute_batch()          │
  │     │   messages += assistant_msg + tool_result_msgs                          │
  │     └─ until no tool_calls → stop_reason=COMPLETED                             │
  └──────────────────────────────────────────────────────────────────────────────┘
                             │
                             ▼
  ┌──────────────────────────────────────────────────────────────────────────────┐
  │ AgentResponse (content, events, stop_reason)                                   │
  └──────────────────────────────────────────────────────────────────────────────┘
                             │
                             ▼
  ┌──────────────────────────────────────────────────────────────────────────────┐
  │ 持久化                                                                        │
  │   scheduler.commit(user_text, assistant_text)                                │
  │   scheduler.save_to_memory(user_text, assistant_text)                         │
  └──────────────────────────────────────────────────────────────────────────────┘
                             │
                             ▼
  ┌──────────────────────────────────────────────────────────────────────────────┐
  │ 返回 AgentResponse → Channel 发送 / 流式 yield                                │
  └──────────────────────────────────────────────────────────────────────────────┘
```

---

## 设计原则

### 原则优先级

| 优先级 | 原则 | 适用场景 |
|--------|------|----------|
| P0 | 单一职责、代码即文档、显式优于隐式 | 所有代码 |
| P1 | 依赖倒置、组合优于继承、失败快速、测试驱动 | 架构设计 |
| P2 | 接口隔离、开放封闭、最小惊讶 | API 设计 |
| P3 | 不可变性优先、轻量化设计 | 状态管理 |

---

## 核心原则

### I. 代码即文档

**核心理念**：类型提示 + 文档字符串自解释，命名语义化，避免隐式逻辑。

```python
# ✅ 类型提示 + Pydantic 即文档
from pydantic import BaseModel, Field
from typing import Protocol, Any, runtime_checkable

@runtime_checkable
class Tool(Protocol):
    name: str
    description: str
    input_schema: type[BaseModel]
    
    async def execute(self, input_: Any, ctx: "ToolContext") -> Any:
        """执行工具逻辑"""
        ...

# 使用 Pydantic 定义输入契约
class SearchInput(BaseModel):
    query: str = Field(..., description="搜索关键词", min_length=1)
    limit: int = Field(default=10, ge=1, le=100, description="返回结果数")

# ❌ 需要额外注释说明
def tool(name, desc, schema, run_fn):  # 参数含义？schema 格式？
    ...
```

**实践要点**：
- 使用 `typing` 模块和 Pydantic 明确输入输出契约
- 函数/方法必须包含 [Google/NumPy 风格](https://sphinxcontrib-napoleon.readthedocs.io/) docstring
- 避免缩写，除非是业界共识（如 `LLM`、`API`、`URL`）
- 类型提示即是最准确的文档，配合 `mypy --strict` 强制检查

---

### II. 单一职责原则

**核心理念**：一个模块只做一件事，一个函数只完成一个目标。

```python
# ❌ 职责混杂
class UserManager:
    def create_user(self, ...): ...
    def send_email(self, ...): ...      # 邮件逻辑
    def log_activity(self, ...): ...    # 日志逻辑

# ✅ 职责分离 + 依赖注入
class UserService:
    def __init__(self, repo: UserRepository, notifier: EmailService):
        self._repo = repo
        self._notifier = notifier
    
    def create_user(self, ...):
        user = self._repo.save(...)
        self._notifier.send_welcome(user)
        return user

class EmailService:
    async def send_welcome(self, user: User) -> None: ...

class ActivityLogger:
    def log(self, event: str, meta: dict) -> None: ...
```

**实践要点**：
- 类/模块只负责一个业务领域（SRP）
- 方法只完成一个明确的目标，复杂逻辑拆分为私有方法
- 使用 `@staticmethod` / `@classmethod` 区分纯函数与工厂方法

---

### III. 显式优于隐式

**核心理念**：行为意图清晰可见，避免魔法和隐式约定。

```python
# ❌ 隐式行为：transform 从哪来？全局变量？
def process(data: list[dict]) -> list:
    return [transform(item) for item in data]

# ✅ 显式依赖：通过参数传递
from typing import Callable, TypeVar
T = TypeVar('T')

def process(
    data: list[dict], 
    transform: Callable[[dict], T]
) -> list[T]:
    return [transform(item) for item in data]

# ✅ 配置项通过数据类显式传入
from dataclasses import dataclass

@dataclass(frozen=True)
class ProcessConfig:
    batch_size: int = 32
    timeout_sec: float = 30.0

def process_with_config(data: list[dict], config: ProcessConfig) -> ...:
    ...
```

**实践要点**：
- 依赖关系通过参数/构造函数显式传递
- 避免全局变量和隐式上下文（可用 `contextvars` 替代）
- 配置项使用 `@dataclass(frozen=True)` 或 Pydantic 管理

---

### IV. 失败快速原则

**核心理念**：尽早暴露错误，避免错误传播。

```python
# ❌ 错误延迟暴露
async def execute(tool: Tool) -> Any:
    result = await tool.execute(...)
    if result is None:
        raise RuntimeError("执行失败")  # 问题源头已丢失
    return result

# ✅ 前置校验 + 明确异常
class ToolExecutionError(Exception): ...

def execute(tool: Tool, input_: Any, ctx: ToolContext) -> Any:
    if tool is None:
        raise ValueError("tool 不能为 None")
    if not hasattr(tool, "execute") or not callable(tool.execute):
        raise ToolExecutionError(f"工具 {tool} 未实现 execute 方法")
    
    # 使用 Pydantic 校验输入
    if hasattr(tool, "input_schema"):
        validated = tool.input_schema.model_validate(input_data)
        return tool.execute(validated, ctx)
```

**实践要点**：
- 入口处使用 `assert`（开发环境）+ 显式 `if-raise`（生产环境）校验参数
- 定义领域异常类（如 `ToolExecutionError`），避免裸 `Exception`
- 不吞没错误，使用 `raise ... from original` 保留异常链

---

## SOLID 原则

### V. 组合优于继承

**核心理念**：通过组合 + 事件总线解耦，避免继承链导致的循环依赖。

```python
# ❌ 继承导致循环依赖
class BaseChannel:
    def __init__(self, agent: "Agent"):  # 前向引用
        self.agent = agent

class Agent:
    def __init__(self):
        self.channels: list[BaseChannel] = []  # 循环引用

# ✅ 组合 + 事件总线解耦
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

@runtime_checkable
class EventHandler(Protocol):
    async def handle(self, event: "Event") -> None: ...

class EventBus:
    def __init__(self):
        self._handlers: dict[type[Event], list[EventHandler]] = {}
    
    def subscribe(self, event_type: type[Event], handler: EventHandler) -> None:
        self._handlers.setdefault(event_type, []).append(handler)
    
    async def publish(self, event: Event) -> None:
        for handler in self._handlers.get(type(event), []):
            await handler.handle(event)

# 渠道实现只依赖 EventBus
class FeishuChannel:
    def __init__(self, event_bus: EventBus):
        event_bus.subscribe(MessageOutboundEvent, self._send_message)
    
    async def _send_message(self, event: MessageOutboundEvent) -> None:
        # 调用飞书 API 发送
        ...
```

**实践要点**：
- 模块间通过 `EventBus` / `MessageQueue` 通信，不直接引用
- 依赖注入通过构造函数或 `dependency-injector` 等库管理
- 使用 `typing.Protocol` + `@runtime_checkable` 定义鸭子类型契约

---

### VI. 开放封闭原则

**核心理念**：对扩展开放，对修改封闭，使用注册表模式实现插件式扩展。

```python
from typing import ClassVar

class ToolRegistry:
    _tools: ClassVar[dict[str, type["Tool"]]] = {}
    
    @classmethod
    def register(cls, tool_cls: type["Tool"], name: str | None = None) -> None:
        """装饰器风格注册：@ToolRegistry.register(MyTool)"""
        key = name or tool_cls.__name__
        if key in cls._tools:
            raise ValueError(f"工具 {key} 已注册")
        cls._tools[key] = tool_cls
    
    @classmethod
    def get(cls, name: str, **init_kwargs) -> "Tool | None":
        tool_cls = cls._tools.get(name)
        return tool_cls(**init_kwargs) if tool_cls else None

# 使用方式
@ToolRegistry.register(name="web_search")
class WebSearchTool(BaseTool):
    name = "web_search"
    input_schema = SearchInput
    
    async def execute(self, input_: SearchInput, ctx: ToolContext) -> SearchResults:
        ...
```

**实践要点**：
- 使用类方法/装饰器实现动态注册，避免硬编码
- 通过依赖注入解耦组件，支持测试时 mock
- 通过事件系统/插件机制实现松耦合通信

---

### VII. 依赖倒置原则

**核心理念**：高层模块不依赖低层模块，两者都依赖抽象。

```python
# ❌ 高层依赖具体实现
class Agent:
    def __init__(self):
        self.llm = OpenAIProvider(api_key="...")  # 硬编码供应商

# ✅ 依赖抽象接口 + 构造函数注入
from abc import ABC, abstractmethod

class LLMProvider(ABC):
    @abstractmethod
    async def generate(self, prompt: str, **kwargs) -> str:
        ...

class Agent:
    def __init__(self, llm: LLMProvider, tools: list[Tool]):
        self._llm = llm
        self._tools = {t.name: t for t in tools}
    
    async def run(self, query: str) -> str:
        # 使用 self._llm 和 self._tools
        ...

# 工厂函数组装（Composition Root）
def create_agent(config: AppConfig) -> Agent:
    llm = OpenAIProvider(config.openai_key) if config.provider == "openai" else DeepSeekProvider(...)
    tools = [WebSearchTool(), CalculatorTool()]
    return Agent(llm=llm, tools=tools)
```

**实践要点**：
- 依赖抽象基类（`abc.ABC`）或 `Protocol`，而非具体实现
- 通过构造函数注入依赖，便于单元测试 mock
- 使用工厂函数或 DI 容器（如 `dependency-injector`）管理对象生命周期

---

### VIII. 接口隔离原则

**核心理念**：不应强迫客户端依赖它不使用的方法。

```python
# ❌ 臃肿接口
class Worker(Protocol):
    def work(self) -> None: ...
    def eat(self) -> None: ...      # 机器人不需要？
    def sleep(self) -> None: ...    # 无状态服务不需要？

# ✅ 接口分离 + 多继承组合
class Workable(Protocol):
    async def work(self, task: Task) -> Result: ...

class Maintainable(Protocol):
    def schedule_maintenance(self, interval: timedelta) -> None: ...

# 具体实现按需组合
class HumanWorker:
    def work(self, task: Task) -> Result: ...
    def eat(self) -> None: ...
    def sleep(self) -> None: ...

class RobotWorker:
    def __init__(self, maint: Maintainable):
        self._maint = maint
    def work(self, task: Task) -> Result: ...  # 只需实现 Workable
```

**实践要点**：
- 接口按职责拆分，保持精简（单一方法或紧密相关方法组）
- 客户端只依赖需要的 `Protocol`，使用多继承组合能力
- 避免创建"上帝接口"，警惕 `**kwargs` 滥用

---

## 实践原则

### IX. 轻量化设计

**核心理念**：最小依赖，最小抽象，无过度工程。

| 约束 | 阈值 | 原因 |
|------|------|------|
| 单文件行数 | ≤ 400 行 | PEP 8 可读性 + 便于 review |
| 单函数行数 | ≤ 30 行 | 单一职责，易于测试 |
| 函数嵌套层级 | ≤ 3 层 | 避免复杂度爆炸，可用提前 return 优化 |
| 函数参数 | ≤ 5 个 | 过多应封装为 `@dataclass` 或 Pydantic 模型 |
| 继承层级 | ≤ 2 层 | 优先组合，避免深度继承链 |

```python
# ❌ 过度抽象（Python 风格反模式）
from abc import ABC, abstractmethod

class BaseHandler(ABC):
    @abstractmethod
    def handle(self) -> None: ...
    @abstractmethod
    def parse(self) -> None: ...

class AbstractMessageHandler(BaseHandler):
    def __init__(self, config: dict): ...
    # ... 多层抽象

class HandlerImpl(AbstractMessageHandler):
    def handle(self) -> None: ...

# ✅ 最小抽象 + Protocol
class Handler(Protocol):
    def handle(self, msg: Message) -> None: ...

class MessageHandler:
    def handle(self, msg: Message) -> None:
        # 直接实现，必要时提取私有方法
        parsed = self._parse(msg)
        self._process(parsed)
    
    def _parse(self, msg: Message) -> ParsedMsg: ...
    def _process(self, parsed: ParsedMsg) -> None: ...
```

---

### X. 零技术债务

**核心理念**：及时清除遗留代码和弃用代码，避免新旧代码共存。

```python
# ❌ 新旧代码共存 + 隐式兼容
def process(data: Any, legacy_mode: bool = False) -> Any:
    if legacy_mode:
        warnings.warn("legacy_mode 已废弃，将在 v2.0 移除", DeprecationWarning)
        return _legacy_process(data)  # 增加维护负担
    return _new_process(data)

# ✅ 干净迁移 + 显式废弃
def process(data: Any) -> Any:
    """处理数据（v2.0+）"""
    return _new_process(data)

# 如需兼容，使用独立函数 + 明确废弃标记
@deprecated("Use `process` instead. Will be removed in v2.0.")
def legacy_process(data: Any) -> Any:  # type: ignore
    return _legacy_process(data)
```

**实践要点**：
- 重构后立即删除旧代码，不保留"兼容层"（除非有明确迁移计划）
- 使用 `@deprecated` 装饰器（如 `boltons` 或自定义）标记废弃项
- 注释掉的代码块直接删除，Git 历史可追溯
- 重构时同步更新所有调用点 + 文档，不留"过渡期"

---

### XI. 最小惊讶原则

**核心理念**：API 行为应符合直觉预期，避免意外结果。

```python
# ❌ 意外行为：函数名 getUser 却可能创建用户
def get_user(user_id: str) -> User | None:
    if not user_id:
        return create_user()  # 副作用！调用者意料之外

# ✅ 符合预期：函数名准确描述行为
def get_user(user_id: str) -> User | None:
    """获取用户，不存在则返回 None"""
    if not user_id:
        return None
    return _repo.find_by_id(user_id)

def get_or_create_user(user_id: str) -> User:
    """获取或创建用户（显式命名）"""
    return _repo.find_by_id(user_id) or _repo.create(id=user_id)
```

**实践要点**：
- 函数名准确描述行为（`get` / `create` / `get_or_create` 语义分离）
- 参数和返回值符合直觉（避免 `**kwargs` 隐藏必要参数）
- 避免副作用和隐藏状态，纯函数优先

---

### XII. 不可变性优先

**核心理念**：优先使用不可变数据，减少副作用。

```python
from dataclasses import dataclass, replace
from typing import Final

# ✅ 使用 frozen dataclass + replace 更新
@dataclass(frozen=True)
class AgentState:
    step: int = 0
    context: dict[str, Any] = None  # 注意：可变默认值需谨慎
    
    def next_step(self, **updates) -> "AgentState":
        return replace(self, step=self.step + 1, **updates)

# ✅ 使用 Final 标记常量
MAX_RETRY: Final[int] = 3
DEFAULT_CONFIG: Final[dict] = {"timeout": 30}  # 注意：dict 本身仍可修改

# ❌ 可变状态（易引发 bug）
state = {"count": 0}
state["count"] += 1  # 多处修改难追踪
```

**实践要点**：
- 使用 `@dataclass(frozen=True)` 或 Pydantic `ConfigDict(frozen=True)` 定义不可变对象
- 使用 `replace()`（dataclass）或 `model_copy(update={})`（Pydantic v2）创建新实例
- 避免直接修改传入的 list/dict，必要时 `copy.deepcopy()` 或返回新对象
- 使用 `typing.Final` 标记不应重新绑定的变量

---

### XIII. 测试驱动

**核心理念**：先写测试，后写实现，用测试定义行为契约。

```python
# ✅ 测试先行 - 使用 pytest + pytest-asyncio
# tests/test_tool_registry.py
import pytest
from agent.tools import ToolRegistry, Tool

@pytest.mark.asyncio
async def test_tool_registry_register_and_get():
    registry = ToolRegistry()
    
    # 使用 Protocol 模拟 Tool
    class MockTool:
        name = "mock"
        async def execute(self, input_data, ctx):
            return "ok"
    
    tool = MockTool()
    registry.register(MockTool, name="mock")
    
    retrieved = registry.get("mock")
    assert retrieved is not None
    assert await retrieved.execute(None, None) == "ok"

# 然后实现代码（满足测试）
# agent/tools/registry.py
class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, type[Tool]] = {}
    
    def register(self, tool_cls: type[Tool], name: str | None = None) -> None:
        key = name or tool_cls.__name__
        self._tools[key] = tool_cls
    
    def get(self, name: str, **init_kwargs) -> Tool | None:
        cls = self._tools.get(name)
        return cls(**init_kwargs) if cls else None
```

**实践要点**：
- 使用 `pytest` + `pytest-asyncio`，测试文件名 `test_*.py` 或 `*_test.py`
- 修改代码前先更新/新增测试，确保测试覆盖新行为
- 测试失败时立即修复，不积累测试债务
- 保持测试简洁：一个 `test_*` 函数只验证一个行为
- 使用 `unittest.mock` 或 `pytest-mock` 隔离外部依赖
- 重构代码时测试作为安全网，确保行为不变（CI 中强制 `pytest --cov`）

---

## Python 专属开发规范

### 项目结构规范

```
my_agent_project/
├── pyproject.toml          # 项目配置（poetry/uv/pip-tools）
├── README.md
├── src/
│   └── agent/              # 主包（避免 src/agent/agent 嵌套）
│       ├── __init__.py
│       ├── core/           # 核心抽象：Agent, Tool, EventBus
│       ├── tools/          # 具体工具实现
│       ├── channels/       # 通信渠道：Feishu, Slack, API
│       └── utils/          # 纯函数工具
├── tests/
│   ├── unit/               # 单元测试
│   ├── integration/        # 集成测试（依赖外部服务）
│   └── conftest.py         # pytest 共享 fixture
├── scripts/                # 运维脚本：deploy.py, migrate.py
└── docs/                   # Sphinx/MkDocs 文档
```

---

### 命名与代码风格

| 类型 | 规范 | 示例 | 依据 |
|------|------|------|------|
| 模块/包 | snake_case, 短小 | `tool_registry.py`, `agents/` | PEP 8 |
| 类名 | PascalCase | `WebSearchTool`, `AgentOrchestrator` | PEP 8 |
| 函数/变量 | snake_case | `get_user_by_id`, `max_retry_count` | PEP 8 |
| 常量 | UPPER_SNAKE_CASE | `DEFAULT_TIMEOUT_SEC`, `LLM_PROVIDERS` | PEP 8 |
| 私有成员 | 前缀单下划线 | `_internal_cache`, `_validate_input()` | 约定俗成 |
| 缩写 | 仅业界共识 | `LLM`, `API`, `URL`, `ID` | 可读性优先 |

**工具链强制配置**（`pyproject.toml`）：

```toml
[tool.ruff]
line-length = 100
select = ["E", "F", "I", "UP", "RUF"]  # flake8 + isort + pyupgrade + ruff 自有规则

[tool.mypy]
python_version = "3.10"
strict = true  # 启用所有严格检查
disallow_any_generics = false  # 按需放宽

[tool.pytest.ini_options]
asyncio_mode = "auto"
addopts = "--cov=src/agent --cov-report=term-missing"
```

---

### 文档字符串规范（Google Style）

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

### 依赖管理规范

| 场景 | 推荐方案 | 命令示例 |
|------|----------|----------|
| 新项目 | `uv` (最快) 或 `poetry` | `uv init && uv add pydantic httpx` |
| 企业项目 | `pip-tools` + requirements | `pip-compile pyproject.toml` |
| 可选依赖 | `pyproject.toml` extras | `uv add --optional dev pytest mypy` |
| 锁定版本 | 始终提交 lock 文件 | `uv.lock` / `poetry.lock` / `requirements.txt` |

**依赖原则**：
- 核心依赖 ≤ 15 个，避免"依赖地狱"
- 优先选择活跃维护、类型提示完善的库（如 `pydantic`, `httpx`, `structlog`）
- 异步生态统一：`asyncio` + `httpx` + `asyncpg`，避免混用 `requests`/`sync` 库

---

### 异常处理规范

```python
# 定义领域异常基类
class AgentError(Exception):
    """Agent 系统基础异常"""
    def __init__(self, message: str, context: dict | None = None):
        super().__init__(message)
        self.context = context or {}

# 具体异常继承 + 明确场景
class ToolExecutionError(AgentError): ...
class LLMRateLimitError(AgentError): ...
class ConfigurationError(AgentError): ...

# 使用：捕获具体异常，向上抛领域异常
async def safe_execute(tool: Tool, input_: Any) -> Any:
    try:
        return await tool.execute(input_data)
    except httpx.TimeoutException as e:
        raise ToolExecutionError(
            f"工具 {tool.name} 执行超时", 
            context={"input": input_data}
        ) from e
    except pydantic.ValidationError as e:
        raise ValueError(f"输入校验失败：{e}") from e  # 客户端错误，不包装
```

---

### 异步编程规范

```python
# ✅ 正确：async/await 贯穿 + 资源管理
class AsyncResource:
    async def __aenter__(self): ...
    async def __aexit__(self, *args): ...

async def process_batch(items: list[Item]) -> list[Result]:
    async with AsyncResource() as resource:  # 自动清理
        tasks = [resource.process(item) for item in items]
        return await asyncio.gather(*tasks, return_exceptions=True)

# ❌ 避免：混用 sync/async + 阻塞调用
def bad_process():
    response = requests.get(...)  # 阻塞事件循环！
    return asyncio.run(async_func())  # 嵌套事件循环风险
```

**关键实践**：
- 所有 I/O 操作（网络/DB/文件）必须 `async` + 使用异步库（`httpx`, `aiofiles`, `asyncpg`）
- 使用 `asyncio.gather(..., return_exceptions=True)` 批量处理 + 容错
- 避免在 async 函数中调用同步阻塞代码，必要时用 `asyncio.to_thread()` 卸载
- 使用 `contextlib.asynccontextmanager` 管理异步资源生命周期

**MindBot 专属约束**：
- `MindBot` 与 `MindAgent` 所有公开方法均为 `async def`，不提供同步版本
- CLI 命令（typer）通过 `asyncio.run()` 作为唯一同步入口，不在内部嵌套
- Tracer 文件写入使用 `asyncio.to_thread()` 卸载，不阻塞事件循环
- 禁止在新功能中添加同步 chat 包装，历史兼容层统一标记 `DeprecationWarning`

---

## 附：Python Agent 开发 Checklist

```markdown
## 代码质量
- [ ] 通过 `ruff check .` 和 `mypy src/` 无错误
- [ ] 所有 public 函数/类包含 Google style docstring
- [ ] 类型提示完整，无 `Any` 滥用（必要时用 `# type: ignore` + 说明）
- [ ] 无 `print()` / `pdb` 残留，使用 `structlog` 或 `logging` 

## 测试覆盖
- [ ] 新增功能包含单元测试（pytest）
- [ ] 异步函数使用 `@pytest.mark.asyncio`
- [ ] 外部依赖使用 `pytest-mock` 隔离
- [ ] CI 中强制 `pytest --cov --cov-fail-under=80`

## 可维护性
- [ ] 单文件 ≤ 400 行，复杂模块拆分子包
- [ ] 无循环导入（可用 `importlib` 延迟导入或重构）
- [ ] 配置项集中管理（Pydantic Settings + 环境变量）
- [ ] 敏感信息通过 `SecretStr` + 环境变量注入，不硬编码

## 部署友好
- [ ] `pyproject.toml` 包含完整 metadata 和 entry-points
- [ ] 提供 `Dockerfile` + `.dockerignore`（多阶段构建）
- [ ] 健康检查端点 `/health` 返回依赖状态（DB/LLM/Tools）
- [ ] 日志结构化（JSON 格式），便于 ELK/Sentry 收集
```

---

## 快速开始模板

```bash
# 1. 初始化项目（使用 uv）
uv init my-agent && cd my-agent
uv add pydantic httpx structlog fastapi
uv add --optional dev pytest pytest-asyncio mypy ruff

# 2. 创建核心模块
mkdir -p src/agent/{core,tools,channels,utils}
touch src/agent/{__init__.py,core/__init__.py,tools/__init__.py}

# 3. 编写第一个 Tool
cat > src/agent/tools/hello.py << 'EOF'
from pydantic import BaseModel, Field
from agent.core import Tool, ToolContext

class HelloInput(BaseModel):
    name: str = Field(..., description="用户姓名")

class HelloTool(Tool):
    name = "hello"
    description = "返回问候语"
    input_schema = HelloInput
    
    async def execute(self, input_: HelloInput, ctx: ToolContext) -> str:
        return f"Hello, {input_.name}! 🤖"
EOF

# 4. 运行测试
uv run pytest tests/ -v
```

---

> 📌 **核心总结**：Python 版 Agent 开发 = **类型安全（Pydantic + mypy） + 显式依赖（构造函数注入） + 异步优先（asyncio） + 测试驱动（pytest）**。设计原则跨语言通用，但工程实践必须尊重 Python 社区惯例（PEP 8、duck typing、batteries-included 哲学）。

---

*文档版本：v1.1 | 最后更新：2026-03 | 维护者：RunkeZhong*