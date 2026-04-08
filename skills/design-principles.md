# MindBot 设计原则详细指南

> 本文件从 AGENTS.md 拆分，提供设计原则的详细说明和代码示例。
> AGENTS.md 中的铁律约束（chat 接口、主链路、全异步等）优先级高于本文。

---

## 原则优先级

| 优先级 | 原则 | 适用场景 |
|--------|------|----------|
| P0 | 单一职责、代码即文档、显式优于隐式 | 所有代码 |
| P1 | 依赖倒置、组合优于继承、失败快速、测试驱动 | 架构设计 |
| P2 | 接口隔离、开放封闭、最小惊讶 | API 设计 |
| P3 | 不可变性优先、轻量化设计 | 状态管理 |

---

## I. 代码即文档

**核心理念**：类型提示 + 文档字符串自解释，命名语义化，避免隐式逻辑。

```python
# OK — 类型提示 + Pydantic 即文档
from pydantic import BaseModel, Field
from typing import Protocol, runtime_checkable

@runtime_checkable
class Tool(Protocol):
    name: str
    description: str
    input_schema: type[BaseModel]

    async def execute(self, input_: Any, ctx: "ToolContext") -> Any:
        ...

class SearchInput(BaseModel):
    query: str = Field(..., description="搜索关键词", min_length=1)
    limit: int = Field(default=10, ge=1, le=100, description="返回结果数")

# BAD — 需要额外注释说明
def tool(name, desc, schema, run_fn):
    ...
```

**实践要点**：

- 使用 `typing` 模块和 Pydantic 明确输入输出契约
- 函数/方法必须包含 Google/NumPy 风格 docstring
- 避免缩写，除非是业界共识（LLM、API、URL）
- 类型提示配合 `mypy --strict` 强制检查

---

## II. 单一职责原则

**核心理念**：一个模块只做一件事，一个函数只完成一个目标。

```python
# BAD — 职责混杂
class UserManager:
    def create_user(self, ...): ...
    def send_email(self, ...): ...      # 邮件逻辑
    def log_activity(self, ...): ...    # 日志逻辑

# OK — 职责分离 + 依赖注入
class UserService:
    def __init__(self, repo: UserRepository, notifier: EmailService):
        self._repo = repo
        self._notifier = notifier

    def create_user(self, ...):
        user = self._repo.save(...)
        self._notifier.send_welcome(user)
        return user
```

**实践要点**：

- 类/模块只负责一个业务领域
- 方法只完成一个明确的目标，复杂逻辑拆分为私有方法
- 使用 `@staticmethod` / `@classmethod` 区分纯函数与工厂方法

---

## III. 显式优于隐式

**核心理念**：行为意图清晰可见，避免魔法和隐式约定。

```python
# BAD — 隐式行为
def process(data: list[dict]) -> list:
    return [transform(item) for item in data]  # transform 从哪来？

# OK — 显式依赖
def process(data: list[dict], transform: Callable[[dict], T]) -> list[T]:
    return [transform(item) for item in data]

# OK — 配置项通过 dataclass 显式传入
@dataclass(frozen=True)
class ProcessConfig:
    batch_size: int = 32
    timeout_sec: float = 30.0
```

**实践要点**：

- 依赖关系通过参数/构造函数显式传递
- 避免全局变量和隐式上下文（可用 `contextvars` 替代）
- 配置项使用 `@dataclass(frozen=True)` 或 Pydantic 管理

---

## IV. 失败快速原则

**核心理念**：尽早暴露错误，避免错误传播。

```python
# BAD — 错误延迟暴露
async def execute(tool: Tool) -> Any:
    result = await tool.execute(...)
    if result is None:
        raise RuntimeError("执行失败")  # 问题源头已丢失

# OK — 前置校验 + 明确异常
class ToolExecutionError(Exception): ...

def execute(tool: Tool, input_: Any, ctx: ToolContext) -> Any:
    if tool is None:
        raise ValueError("tool 不能为 None")
    if not hasattr(tool, "execute") or not callable(tool.execute):
        raise ToolExecutionError(f"工具 {tool} 未实现 execute 方法")

    if hasattr(tool, "input_schema"):
        validated = tool.input_schema.model_validate(input_data)
        return tool.execute(validated, ctx)
```

**实践要点**：

- 入口处使用显式 `if-raise` 校验参数
- 定义领域异常类，避免裸 `Exception`
- 不吞没错误，使用 `raise ... from original` 保留异常链

---

## V. 组合优于继承

**核心理念**：通过组合 + 事件总线解耦，避免继承链导致的循环依赖。

```python
# BAD — 继承导致循环依赖
class BaseChannel:
    def __init__(self, agent: "Agent"):
        self.agent = agent

class Agent:
    def __init__(self):
        self.channels: list[BaseChannel] = []  # 循环引用

# OK — 组合 + EventBus 解耦
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

class FeishuChannel:
    def __init__(self, event_bus: EventBus):
        event_bus.subscribe(MessageOutboundEvent, self._send_message)
```

**实践要点**：

- 模块间通过 `EventBus` / `MessageQueue` 通信，不直接引用
- 依赖注入通过构造函数管理
- 使用 `typing.Protocol` + `@runtime_checkable` 定义鸭子类型契约

---

## VI. 开放封闭原则

**核心理念**：对扩展开放，对修改封闭，使用注册表模式实现插件式扩展。

```python
class ToolRegistry:
    _tools: ClassVar[dict[str, type["Tool"]]] = {}

    @classmethod
    def register(cls, tool_cls: type["Tool"], name: str | None = None) -> None:
        key = name or tool_cls.__name__
        if key in cls._tools:
            raise ValueError(f"工具 {key} 已注册")
        cls._tools[key] = tool_cls

    @classmethod
    def get(cls, name: str, **init_kwargs) -> "Tool | None":
        tool_cls = cls._tools.get(name)
        return tool_cls(**init_kwargs) if tool_cls else None

# 使用
@ToolRegistry.register(name="web_search")
class WebSearchTool(BaseTool):
    ...
```

---

## VII. 依赖倒置原则

**核心理念**：高层模块不依赖低层模块，两者都依赖抽象。

```python
# BAD — 高层依赖具体实现
class Agent:
    def __init__(self):
        self.llm = OpenAIProvider(api_key="...")

# OK — 依赖抽象 + 构造函数注入
class LLMProvider(ABC):
    @abstractmethod
    async def generate(self, prompt: str, **kwargs) -> str: ...

class Agent:
    def __init__(self, llm: LLMProvider, tools: list[Tool]):
        self._llm = llm
        self._tools = {t.name: t for t in tools}

# 工厂函数组装
def create_agent(config: AppConfig) -> Agent:
    llm = OpenAIProvider(config.openai_key)
    tools = [WebSearchTool(), CalculatorTool()]
    return Agent(llm=llm, tools=tools)
```

---

## VIII. 接口隔离原则

**核心理念**：不应强迫客户端依赖它不使用的方法。

```python
# BAD — 臃肿接口
class Worker(Protocol):
    def work(self) -> None: ...
    def eat(self) -> None: ...      # 机器人不需要
    def sleep(self) -> None: ...    # 无状态服务不需要

# OK — 接口分离 + 多继承组合
class Workable(Protocol):
    async def work(self, task: Task) -> Result: ...

class Maintainable(Protocol):
    def schedule_maintenance(self, interval: timedelta) -> None: ...
```

---

## IX. 轻量化设计

| 约束 | 阈值 | 原因 |
|------|------|------|
| 单文件行数 | <= 400 行 | PEP 8 可读性 + 便于 review |
| 单函数行数 | <= 30 行 | 单一职责，易于测试 |
| 函数嵌套层级 | <= 3 层 | 避免复杂度爆炸 |
| 函数参数 | <= 5 个 | 过多应封装为 dataclass 或 Pydantic 模型 |
| 继承层级 | <= 2 层 | 优先组合 |

```python
# BAD — 过度抽象
class BaseHandler(ABC):
    @abstractmethod
    def handle(self) -> None: ...
    @abstractmethod
    def parse(self) -> None: ...

class AbstractMessageHandler(BaseHandler):
    def __init__(self, config: dict): ...

class HandlerImpl(AbstractMessageHandler):
    def handle(self) -> None: ...

# OK — 最小抽象 + Protocol
class Handler(Protocol):
    def handle(self, msg: Message) -> None: ...

class MessageHandler:
    def handle(self, msg: Message) -> None:
        parsed = self._parse(msg)
        self._process(parsed)
```

---

## X. 零技术债务

```python
# BAD — 新旧代码共存
def process(data: Any, legacy_mode: bool = False) -> Any:
    if legacy_mode:
        return _legacy_process(data)
    return _new_process(data)

# OK — 干净迁移
def process(data: Any) -> Any:
    return _new_process(data)

# 如需兼容，使用独立函数 + 明确废弃标记
@deprecated("Use `process` instead. Will be removed in v2.0.")
def legacy_process(data: Any) -> Any:
    return _legacy_process(data)
```

**实践要点**：

- 重构后立即删除旧代码，不保留兼容层
- 注释掉的代码块直接删除，Git 历史可追溯
- 重构时同步更新所有调用点

---

## XI. 最小惊讶原则

```python
# BAD — 函数名 getUser 却可能创建用户
def get_user(user_id: str) -> User | None:
    if not user_id:
        return create_user()  # 副作用！

# OK — 函数名准确描述行为
def get_user(user_id: str) -> User | None:
    """获取用户，不存在则返回 None"""
    if not user_id:
        return None
    return _repo.find_by_id(user_id)

def get_or_create_user(user_id: str) -> User:
    """获取或创建用户（显式命名）"""
    return _repo.find_by_id(user_id) or _repo.create(id=user_id)
```

---

## XII. 不可变性优先

```python
from dataclasses import dataclass, replace
from typing import Final

# OK — frozen dataclass + replace 更新
@dataclass(frozen=True)
class AgentState:
    step: int = 0

    def next_step(self, **updates) -> "AgentState":
        return replace(self, step=self.step + 1, **updates)

MAX_RETRY: Final[int] = 3

# BAD — 可变状态（易引发 bug）
state = {"count": 0}
state["count"] += 1  # 多处修改难追踪
```

**实践要点**：

- 使用 `@dataclass(frozen=True)` 或 Pydantic `ConfigDict(frozen=True)`
- 使用 `replace()` 或 `model_copy(update={})` 创建新实例
- 避免直接修改传入的 list/dict

---

## XIII. 测试驱动

详见 `skills/testing-guide.md`。

---

*详细设计原则指南 | MindBot v0.3.1*
