---
title: 数据模型
---

# 数据模型

MindBot 在两个模块中定义核心数据模型：

- `mindbot.agent.models` -- Agent 层响应与事件模型
- `mindbot.context.models` -- 消息、工具调用和 Provider 响应模型

---

## Agent 层模型

### AgentResponse

**模块**：`mindbot.agent.models`

Agent 对话执行的完整响应结果。

```python
@dataclass
class AgentResponse:
    content: str
    events: list[AgentEvent] = field(default_factory=list)
    stop_reason: StopReason = StopReason.COMPLETED
    message_trace: list[Message] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
```

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `content` | `str` | - | 最终文本内容 |
| `events` | `list[AgentEvent]` | `[]` | 执行过程中发出的所有事件 |
| `stop_reason` | [`StopReason`](enums.md#stopreason) | `COMPLETED` | 执行终止原因 |
| `message_trace` | `list[Message]` | `[]` | 本轮产生的消息（助手消息和工具结果），按时间顺序排列，不含已有上下文 |
| `metadata` | `dict[str, Any]` | `{}` | 附加元数据 |

#### 方法

##### `add_event()`

```python
def add_event(self, event: AgentEvent) -> None
```

向响应中添加一个事件。

---

### AgentEvent

**模块**：`mindbot.agent.models`

Agent 执行过程中发出的事件，用于流式传输和监控。

```python
@dataclass
class AgentEvent:
    type: EventType
    timestamp: float
    data: dict[str, Any] = field(default_factory=dict)
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | [`EventType`](enums.md#eventtype) | 事件类型 |
| `timestamp` | `float` | 事件发生的 Unix 时间戳 |
| `data` | `dict[str, Any]` | 事件特定数据 |

#### 工厂方法

所有工厂方法自动填充当前时间戳。

| 方法 | 参数 | 返回事件类型 | `data` 内容 |
|------|------|-------------|-------------|
| `thinking(turn)` | `turn: int = 0` | `THINKING` | `{"turn": turn}` |
| `delta(content)` | `content: str` | `DELTA` | `{"content": content}` |
| `tool_call_request(request_id, tool_name, arguments, risk_level)` | 详见下表 | `TOOL_CALL_REQUEST` | `{"request_id", "tool_name", "arguments", "risk_level"}` |
| `tool_call_approved(request_id)` | `request_id: str` | `TOOL_CALL_APPROVED` | `{"request_id": ...}` |
| `tool_call_denied(request_id, reason)` | `request_id: str`, `reason: str = ""` | `TOOL_CALL_DENIED` | `{"request_id", "reason"}` |
| `tool_executing(tool_name, call_id)` | `tool_name: str`, `call_id: str` | `TOOL_EXECUTING` | `{"tool_name", "call_id"}` |
| `tool_result(tool_name, call_id, result)` | `tool_name: str`, `call_id: str`, `result: str` | `TOOL_RESULT` | `{"tool_name", "call_id", "result"}` |
| `user_input_request(question, request_id)` | `question: str`, `request_id: str` | `USER_INPUT_REQUEST` | `{"question", "request_id"}` |
| `user_input_received(input_text)` | `input_text: str` | `USER_INPUT_RECEIVED` | `{"input": input_text}` |
| `complete(stop_reason)` | `stop_reason: StopReason` | `COMPLETE` | `{"stop_reason": ...}` |
| `error(message)` | `message: str` | `ERROR` | `{"message": ...}` |
| `aborted()` | 无 | `ABORTED` | `{}` |

**使用示例**：

```python
from mindbot.agent.models import AgentEvent

# 创建思考事件
event = AgentEvent.thinking(turn=1)

# 创建内容增量事件
event = AgentEvent.delta("你好")

# 创建工具调用请求事件
event = AgentEvent.tool_call_request(
    request_id="req-001",
    tool_name="search",
    arguments={"query": "天气"},
    risk_level="low",
)
```

---

### ToolApprovalRequest

**模块**：`mindbot.agent.models`

工具调用的用户审批请求。

```python
@dataclass
class ToolApprovalRequest:
    request_id: str
    tool_name: str
    arguments: dict[str, Any]
    risk_level: str = "medium"
    reason: str = ""
    timeout: float = 120
```

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `request_id` | `str` | - | 唯一请求标识 |
| `tool_name` | `str` | - | 被调用的工具名称 |
| `arguments` | `dict[str, Any]` | - | 传递给工具的参数 |
| `risk_level` | `str` | `"medium"` | 风险等级：`low` / `medium` / `high` |
| `reason` | `str` | `""` | 需要审批的原因 |
| `timeout` | `float` | `120` | 超时时间（秒） |

---

### InputRequest

**模块**：`mindbot.agent.models`

执行过程中向用户请求输入。

```python
@dataclass
class InputRequest:
    request_id: str
    question: str
    timeout: float = 300
```

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `request_id` | `str` | - | 唯一请求标识 |
| `question` | `str` | - | 向用户提出的问题 |
| `timeout` | `float` | `300` | 超时时间（秒） |

---

### StepOutput

**模块**：`mindbot.agent.models`

单步（一次 LLM 调用 + 工具执行轮）的输出。

```python
@dataclass
class StepOutput:
    turn: int
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    llm_text: str = ""
    reasoning_content: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `turn` | `int` | - | 当前轮次编号 |
| `tool_calls` | `list[ToolCall]` | `[]` | 本步发起的工具调用 |
| `tool_results` | `list[ToolResult]` | `[]` | 本步收到的工具结果 |
| `llm_text` | `str` | `""` | LLM 返回的文本 |
| `reasoning_content` | `str \| None` | `None` | 推理/思维链模型的推理内容 |
| `metadata` | `dict[str, Any]` | `{}` | 步骤元数据 |

---

### TurnResult

**模块**：`mindbot.agent.models`

Agent 循环的最终结果。

```python
@dataclass
class TurnResult:
    final_response: str
    steps: list[StepOutput] = field(default_factory=list)
    stop_reason: StopReason = StopReason.COMPLETED
    metadata: dict[str, Any] = field(default_factory=dict)
```

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `final_response` | `str` | - | 最终回复文本 |
| `steps` | `list[StepOutput]` | `[]` | 所有执行步骤 |
| `stop_reason` | [`StopReason`](enums.md#stopreason) | `COMPLETED` | 终止原因 |
| `metadata` | `dict[str, Any]` | `{}` | 元数据 |

---

### LoopConfig

**模块**：`mindbot.agent.models`

Agent 循环的运行时配置。

```python
@dataclass
class LoopConfig:
    max_turns: int = 10
    max_steps_per_turn: int = 5
    loop_detection_window: int = 3
    enable_auto_continue: bool = True
```

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `max_turns` | `int` | `10` | 最大轮次数 |
| `max_steps_per_turn` | `int` | `5` | 每轮最大步骤数 |
| `loop_detection_window` | `int` | `3` | 连续相同工具调用的检测窗口 |
| `enable_auto_continue` | `bool` | `True` | 是否启用自动继续 |

---

## 上下文层模型

### Message

**模块**：`mindbot.context.models`

跨模块使用的统一多模态消息格式。

```python
@dataclass
class Message:
    role: MessageRole
    content: MessageContent
    tool_calls: list[ToolCall] | None = None
    reasoning_content: str | None = None
    tool_call_id: str | None = None
    turn_id: str | None = None
    iteration: int | None = None
    message_kind: MessageKind | str | None = None
    tool_name: str | None = None
    provider: ProviderInfo | dict[str, Any] | None = None
    usage: UsageInfo | dict[str, Any] | None = None
    finish_reason: str | None = None
    stop_reason: str | None = None
    is_meta: bool = False
    error: str | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)
    token_count: int = 0
```

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `role` | [`MessageRole`](enums.md#messagerole) | - | 消息角色：`"system"` / `"user"` / `"assistant"` / `"tool"` |
| `content` | `str \| list[TextPart \| ImagePart]` | - | 消息内容，支持纯文本或多模态内容列表 |
| `tool_calls` | `list[ToolCall] \| None` | `None` | `role == "assistant"` 时 LLM 请求的工具调用列表 |
| `reasoning_content` | `str \| None` | `None` | 推理模型的思维链内容（需与 tool_calls 一起重发） |
| `tool_call_id` | `str \| None` | `None` | `role == "tool"` 时关联的 `ToolCall.id` |
| `turn_id` | `str \| None` | `None` | 轮次 ID（用于持久化和追踪） |
| `iteration` | `int \| None` | `None` | 迭代编号 |
| `message_kind` | [`MessageKind \| str \| None`](enums.md#messagekind) | `None` | 消息分类标记 |
| `tool_name` | `str \| None` | `None` | 关联的工具名称 |
| `provider` | `ProviderInfo \| dict \| None` | `None` | 产生此消息的 Provider 信息 |
| `usage` | `UsageInfo \| dict \| None` | `None` | Token 使用统计 |
| `finish_reason` | `str \| None` | `None` | LLM 生成停止原因 |
| `stop_reason` | `str \| None` | `None` | Agent 层停止原因 |
| `is_meta` | `bool` | `False` | 是否为元数据消息 |
| `error` | `str \| None` | `None` | 错误信息 |
| `id` | `str` | UUID hex | 唯一消息 ID |
| `timestamp` | `float` | `time.time()` | 消息时间戳 |
| `token_count` | `int` | `0` | 估算的 Token 数量（由 ContextManager 填充） |

#### 属性

##### `text`

```python
@property
def text(self) -> str
```

返回消息内容的纯文本表示。多模态消息中的 `ImagePart` 被替换为 `[image]`。

##### `provider_dict`

```python
@property
def provider_dict(self) -> dict[str, Any] | None
```

返回 Provider 信息为 JSON 安全的字典。

##### `usage_dict`

```python
@property
def usage_dict(self) -> dict[str, Any] | None
```

返回 Usage 信息为 JSON 安全的字典。

---

### ToolCall

**模块**：`mindbot.context.models`

LLM 请求的工具调用。

```python
@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `str` | 工具调用唯一标识 |
| `name` | `str` | 工具名称 |
| `arguments` | `dict[str, Any]` | 传递给工具的参数 |

---

### ToolResult

**模块**：`mindbot.context.models`

工具执行的返回结果。

```python
@dataclass
class ToolResult:
    tool_call_id: str
    success: bool
    content: str = ""
    error: str = ""
```

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `tool_call_id` | `str` | - | 关联的工具调用 ID |
| `success` | `bool` | - | 执行是否成功 |
| `content` | `str` | `""` | 执行结果内容 |
| `error` | `str` | `""` | 错误信息 |

---

### ChatResponse

**模块**：`mindbot.context.models`

所有 LLM Provider 的统一响应格式。

```python
@dataclass
class ChatResponse:
    content: str
    tool_calls: list[ToolCall] | None = None
    reasoning_content: str | None = None
    provider: ProviderInfo | None = None
    finish_reason: FinishReason = FinishReason.STOP
    usage: UsageInfo | None = None
```

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `content` | `str` | - | 响应文本内容 |
| `tool_calls` | `list[ToolCall] \| None` | `None` | LLM 请求的工具调用 |
| `reasoning_content` | `str \| None` | `None` | 推理模型的思维链内容 |
| `provider` | `ProviderInfo \| None` | `None` | 产生此响应的 Provider 信息 |
| `finish_reason` | [`FinishReason`](enums.md#finishreason) | `STOP` | 生成停止原因 |
| `usage` | `UsageInfo \| None` | `None` | Token 使用统计 |

---

### UsageInfo

**模块**：`mindbot.context.models`

单次响应的 Token 使用统计。

```python
@dataclass
class UsageInfo:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
```

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `prompt_tokens` | `int` | `0` | 输入 Token 数 |
| `completion_tokens` | `int` | `0` | 输出 Token 数 |
| `total_tokens` | `int` | `0` | 总 Token 数 |

---

### ProviderInfo

**模块**：`mindbot.context.models`

描述产生响应的 Provider。

```python
@dataclass
class ProviderInfo:
    provider: str
    model: str
    supports_vision: bool = False
    supports_tools: bool = False
```

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `provider` | `str` | - | Provider 类型（如 `"openai"`, `"ollama"`） |
| `model` | `str` | - | 模型名称（如 `"gpt-4o-mini"`） |
| `supports_vision` | `bool` | `False` | 是否支持视觉 |
| `supports_tools` | `bool` | `False` | 是否支持工具 |

---

## 多模态内容类型

### TextPart

```python
@dataclass
class TextPart:
    text: str
    type: Literal["text"] = "text"
```

### ImagePart

```python
@dataclass
class ImagePart:
    data: bytes | str
    mime_type: str = "image/png"
    type: Literal["image"] = "image"
```

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `data` | `bytes \| str` | - | 原始字节、Base64 编码字符串或 URL |
| `mime_type` | `str` | `"image/png"` | MIME 类型 |

### 类型别名

```python
MessageContent = str | list[TextPart | ImagePart]
```

消息内容类型，支持纯文本字符串或多模态内容部件列表。
