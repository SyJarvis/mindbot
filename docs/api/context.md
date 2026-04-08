---
title: 上下文管理
---

# 上下文管理

MindBot 使用基于 **Block（分区）** 的上下文窗口管理机制，将上下文空间划分为 7 个功能分区，各自持有独立的消息列表和 Token 预算。当分区超出预算时，自动应用配置的压缩策略。

---

## ContextManager

**模块**：`mindbot.context.manager`

上下文管理器，负责维护 Block 分区、Token 预算和自动压缩。属于架构第三层（L3 对话域），纯粹处理状态和压缩，不执行跨子系统编排。

### 构造函数

```python
ContextManager(
    config: ContextConfig | None = None,
    *,
    max_tokens: int = 8000,
    strategy: CompressionStrategy | None = None,
) -> None
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `config` | `ContextConfig \| None` | `None` | 上下文配置。为 `None` 时使用 `ContextConfig(max_tokens=max_tokens)` |
| `max_tokens` | `int` | `8000` | 总 Token 预算（仅当 `config` 为 `None` 时生效） |
| `strategy` | `CompressionStrategy \| None` | `None` | 压缩策略。为 `None` 时使用 `TruncateStrategy()` |

---

## Block 分区设计

上下文窗口被划分为 7 个功能 Block，按规范顺序排列。每个 Block 有独立的 Token 预算。

### 默认比例

| Block 名称 | 默认比例 | 说明 |
|-------------|----------|------|
| `system_identity` | 12% | 系统提示词 / 人格设定 |
| `skills_overview` | 8% | 始终可见的技能摘要 |
| `skills_detail` | 15% | 当前轮次选中的技能详细内容 |
| `memory` | 15% | 检索到的记忆块（每轮填充） |
| `conversation` | 35% | 多轮对话历史（压缩目标） |
| `intent_state` | 5% | 可选的轮次级意图/上下文提示 |
| `user_input` | 10% | 当前用户消息 |

Block 预算也可以通过 `ContextBlocksConfig` 显式配置（单位为 Token），此时覆盖默认比例。

---

## ContextBlock

**模块**：`mindbot.context.manager`

单个上下文分区。

```python
@dataclass
class ContextBlock:
    name: str
    max_tokens: int
    messages: list[Message] = field(default_factory=list)
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | `str` | Block 名称 |
| `max_tokens` | `int` | Token 预算上限 |
| `messages` | `list[Message]` | 该 Block 中的消息列表 |

### 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `token_count` | `int` | 当前 Block 中所有消息的总 Token 数 |
| `remaining` | `int` | 剩余可用 Token 数（最小为 0） |

---

## Block 操作方法

### set_system_identity()

```python
def set_system_identity(self, content: str) -> None
```

设置（替换）系统身份 Block 的内容。

### set_skills_overview()

```python
def set_skills_overview(self, content: str | Message | None) -> None
```

设置技能概览 Block。传 `None` 时清空。

### clear_skills_overview()

```python
def clear_skills_overview(self) -> None
```

清空技能概览 Block。

### set_skills_detail()

```python
def set_skills_detail(self, content: str | Message | None) -> None
```

设置技能详情 Block。传 `None` 时清空。

### clear_skills_detail()

```python
def clear_skills_detail(self) -> None
```

清空技能详情 Block。

### set_memory_messages()

```python
def set_memory_messages(self, messages: list[Message]) -> None
```

替换内存 Block 的内容（由 Scheduler 每轮调用）。超出 Block 预算的消息会被截断。

### add_conversation_message()

```python
def add_conversation_message(
    self,
    role: MessageRole,
    content: str,
    **kwargs: Any,
) -> Message
```

创建并追加消息到对话 Block。添加后自动检查并压缩。

### add_conversation()

```python
def add_conversation(self, message: Message) -> None
```

追加已有消息到对话 Block。添加后自动检查并压缩。

### set_intent_state()

```python
def set_intent_state(self, content: str | Message | None) -> None
```

设置意图状态 Block（当前轮次）。传 `None` 时清空。

### clear_intent_state()

```python
def clear_intent_state(self) -> None
```

清空意图状态 Block。

### set_user_input()

```python
def set_user_input(self, message: Message) -> None
```

设置当前轮次的用户输入（单条消息）。

### clear_user_input()

```python
def clear_user_input(self) -> None
```

清空用户输入 Block。

---

## 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `messages` | `list[Message]` | 所有 Block 的消息，按规范顺序合并 |
| `block_names` | `list[str]` | Block 名称列表（规范顺序） |
| `total_tokens` | `int` | 所有 Block 的 Token 总数 |

`messages` 属性也支持赋值（向后兼容），会将内容分配到 `system_identity` 和 `conversation` Block。

---

## 查询方法

### get_block()

```python
def get_block(self, name: str) -> ContextBlock
```

按名称获取 Block。

### get_messages()

```python
def get_messages(self, last_n: int | None = None) -> list[Message]
```

返回规范顺序的所有消息。可选返回最后 `n` 条。

### get_block_messages()

```python
def get_block_messages(self, block_name: str) -> list[Message]
```

返回指定 Block 的消息。

### prepare_for_llm()

```python
def prepare_for_llm(self) -> list[Message]
```

压缩并返回规范顺序的消息，用于 LLM 消费。此方法保留用于向后兼容，主链路使用 `InputBuilder`。

---

## 压缩策略

当 `conversation` Block 超出 Token 预算时，自动调用配置的压缩策略。

### TruncateStrategy

**模块**：`mindbot.context.compression`

丢弃最早的非系统消息，直到满足预算。系统消息始终保留。这是默认策略，无需额外依赖。

```python
class TruncateStrategy(CompressionStrategy):
    def compress(self, messages: list[Message], target_tokens: int) -> list[Message]
```

### SummarizeStrategy

通过 LLM 摘要旧消息，保留最近 `recent_keep` 条原文。

```python
class SummarizeStrategy(CompressionStrategy):
    def __init__(self, llm: ProviderAdapter, recent_keep: int = 4) -> None
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `llm` | `ProviderAdapter` | - | 用于生成摘要的 LLM |
| `recent_keep` | `int` | `4` | 保留最近的原始消息数 |

若 LLM 摘要失败，自动回退到截断策略。

### ExtractStrategy

使用 `KeyInfoExtractor` 提取实体、事实、偏好和行动项，替换旧消息。

```python
class ExtractStrategy(CompressionStrategy):
    def __init__(self, llm: ProviderAdapter, recent_keep: int = 4) -> None
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `llm` | `ProviderAdapter` | - | 用于信息提取的 LLM |
| `recent_keep` | `int` | `4` | 保留最近的原始消息数 |

若提取结果超出预算，自动回退到截断策略。

### MixStrategy

混合策略：同时生成摘要和提取关键信息，然后追加最近的消息原文。

```python
class MixStrategy(CompressionStrategy):
    def __init__(
        self,
        llm: ProviderAdapter,
        recent_keep: int = 4,
        extract_threshold: int = 2,
    ) -> None
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `llm` | `ProviderAdapter` | - | 用于摘要和提取的 LLM |
| `recent_keep` | `int` | `4` | 保留最近的原始消息数 |
| `extract_threshold` | `int` | `2` | 低于此数量的旧消息不执行压缩 |

### ArchiveStrategy

将旧消息移入内存系统，保留引用消息。

```python
class ArchiveStrategy(CompressionStrategy):
    def __init__(
        self,
        memory: MemoryManager,
        recent_keep: int = 4,
    ) -> None
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `memory` | `MemoryManager` | - | 用于持久化归档消息的内存管理器 |
| `recent_keep` | `int` | `4` | 保留最近的原始消息数 |

### 工厂函数

```python
def get_strategy(name: str, **kwargs: Any) -> CompressionStrategy
```

根据名称创建压缩策略。

| 名称 | 必需参数 |
|------|----------|
| `"truncate"` | 无 |
| `"summarize"` | `llm` |
| `"extract"` | `llm` |
| `"mix"` | `llm` |
| `"archive"` | `memory` |

可选参数：`recent_keep`（默认 4）、`extract_threshold`（仅 `mix`，默认 2）。

---

## 工具持久化策略

通过 `ToolPersistenceStrategy` 配置，控制工具调用消息在每轮结束后的持久化方式。

| 策略 | 枚举值 | 说明 |
|------|--------|------|
| `none` | `ToolPersistenceStrategy.NONE` | 不持久化工具消息 |
| `summary` | `ToolPersistenceStrategy.SUMMARY` | 持久化工具消息的摘要 |
| `full` | `ToolPersistenceStrategy.FULL` | 完整持久化所有工具消息 |

配置示例：

```python
from mindbot.config.schema import AgentConfig, ToolPersistenceStrategy

agent_config = AgentConfig(
    tool_persistence=ToolPersistenceStrategy.SUMMARY,
)
```

---

## 检查点机制

ContextManager 支持对当前所有 Block 的状态创建快照（Checkpoint），并在需要时回滚。

### Checkpoint

**模块**：`mindbot.context.checkpoint`

```python
@dataclass
class Checkpoint:
    id: str
    name: str
    messages: list[Message] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `str` | 唯一检查点 ID |
| `name` | `str` | 用户指定的名称 |
| `messages` | `list[Message]` | 快照时的所有消息 |
| `timestamp` | `float` | 创建时间戳 |

### 操作方法

#### create_checkpoint()

```python
def create_checkpoint(self, name: str = "") -> str
```

创建所有 Block 的快照，返回检查点 ID。

#### rollback_to_checkpoint()

```python
def rollback_to_checkpoint(self, checkpoint_id: str) -> None
```

从检查点恢复 Block 内容。若检查点不存在则抛出 `KeyError`。

#### list_checkpoints()

```python
def list_checkpoints(self) -> list[Checkpoint]
```

返回所有检查点列表。

### 使用示例

```python
ctx = ContextManager(max_tokens=8000)

# 创建检查点
cp_id = ctx.create_checkpoint(name="before_tool_use")

# ... 进行对话 ...

# 回滚到检查点
ctx.rollback_to_checkpoint(cp_id)
```

---

## clear()

```python
def clear(self) -> None
```

清空所有 Block 中的消息（保留检查点）。

---

## 使用示例

### 基本使用

```python
from mindbot.context import ContextManager
from mindbot.context.compression import TruncateStrategy

ctx = ContextManager(
    max_tokens=4000,
    strategy=TruncateStrategy(),
)

# 设置系统身份
ctx.set_system_identity("你是一个 AI 助手。")

# 添加对话消息
ctx.add_conversation_message("user", "你好！")
ctx.add_conversation_message("assistant", "你好！有什么可以帮你的吗？")

# 设置用户输入
from mindbot.context.models import Message
ctx.set_user_input(Message(role="user", content="请帮我写一段代码"))

# 获取所有消息（用于发送给 LLM）
messages = ctx.prepare_for_llm()
```

### 使用高级压缩策略

```python
from mindbot.context import ContextManager
from mindbot.context.compression import SummarizeStrategy

# 需要一个 LLM 适配器
llm = create_llm(config)

ctx = ContextManager(
    max_tokens=8000,
    strategy=SummarizeStrategy(llm, recent_keep=6),
)

# 对话超出预算时自动摘要旧消息
for i in range(50):
    ctx.add_conversation_message("user", f"消息 {i}")
    ctx.add_conversation_message("assistant", f"回复 {i}")
```

### 手动压缩

```python
ctx = ContextManager()

# ... 大量对话 ...

# 手动触发压缩
ctx.compact()
```
