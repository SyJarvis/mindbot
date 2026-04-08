# MindBot 消息处理与对话循环深度分析

> 基于 MindBot v0.3.x 源码分析
> 源码位置: `src/mindbot/`

---

## 目录

- [1. 整体架构概览](#1-整体架构概览)
- [2. 消息模型体系](#2-消息模型体系)
- [3. MindAgent — 监督者入口](#3-mindagent--监督者入口)
- [4. Agent — 独立代理](#4-agent--独立代理)
- [5. TurnEngine — 核心对话循环](#5-turnengine--核心对话循环)
- [6. InputBuilder — 消息组装](#6-inputbuilder--消息组装)
- [7. ContextManager — Block 分区上下文管理](#7-contextmanager--block-分区上下文管理)
- [8. 压缩策略](#8-压缩策略)
- [9. 工具执行路径](#9-工具执行路径)
- [10. 持久化写入](#10-持久化写入)
- [11. 完整调用链路图](#11-完整调用链路图)
- [12. 与 Claude Code 的对比与改进方向](#12-与-claude-code-的对比与改进方向)

---

## 1. 整体架构概览

MindBot 采用**四层架构**，每层职责明确：

```
┌─────────────────────────────────────────────────────────────┐
│  MindAgent (agent/core.py, ~378 行)                          │
│  监督者 — 用户入口层                                          │
│  职责: 子代理管理、Session Journal、兼容 API                    │
└────────────────────────┬────────────────────────────────────┘
                         │ chat() / chat_stream()
┌────────────────────────▼────────────────────────────────────┐
│  Agent (agent/agent.py, ~432 行)                             │
│  独立代理 — 会话管理核心                                       │
│  职责: LRU 会话缓存、工具注册、ContextManager/TurnEngine 管理   │
└────────────────────────┬────────────────────────────────────┘
                         │ _run_turn()
┌────────────────────────▼────────────────────────────────────┐
│  TurnEngine (agent/turn_engine.py, ~264 行)                  │
│  对话循环 — for(iteration) 多轮 LLM+工具                       │
│  职责: LLM 调用、工具执行、重复检测、消息轨迹生成                 │
└────────────────────────┬────────────────────────────────────┘
                         │
        ┌────────────────┴────────────────┐
        │                                 │
┌───────▼──────────┐  ┌──────────────────▼───────────────┐
│ InputBuilder     │  │ StreamingExecutor                │
│ (input_builder)  │  │ (streaming.py)                   │
│ 消息组装          │  │ LLM 流式/非流式调用适配             │
└──────────────────┘  └──────────────────────────────────┘
```

**关键文件清单：**

| 文件 | 行数 | 职责 |
|------|------|------|
| `agent/core.py` | ~378 | MindAgent 监督者 |
| `agent/agent.py` | ~432 | Agent 独立代理 |
| `agent/turn_engine.py` | ~264 | 对话循环引擎 |
| `agent/streaming.py` | ~126 | LLM 流式调用适配 |
| `agent/input_builder.py` | ~190 | 消息组装 |
| `agent/models.py` | ~264 | 数据模型定义 |
| `agent/persistence_writer.py` | ~216 | 统一持久化写入 |
| `context/manager.py` | ~441 | Block 分区上下文管理 |
| `context/models.py` | ~149 | 消息/工具模型 |
| `context/compression.py` | ~295 | 压缩策略 |
| `providers/adapter.py` | ~91 | Provider 统一适配 |

---

## 2. 消息模型体系

### 2.1 Message — 统一消息格式

```python
# context/models.py
class Message:
    """Unified multimodal message format used across all modules."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[TextPart | ImagePart]  # 支持多模态

    # assistant 消息携带工具调用
    tool_calls: list[ToolCall] | None = None

    # thinking 模型的推理内容（需随 assistant+tool_calls 重发）
    reasoning_content: str | None = None

    # tool 消息回指 ToolCall.id
    tool_call_id: str | None = None

    # 元数据
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)
    token_count: int = 0  # 估算值，由 ContextManager 填充
```

### 2.2 工具调用模型

```python
# context/models.py
@dataclass
class ToolCall:
    """LLM 请求的工具调用。"""
    id: str
    name: str
    arguments: dict[str, Any]

@dataclass
class ToolResult:
    """工具执行结果。"""
    tool_call_id: str
    success: bool
    content: str = ""
    error: str = ""
```

### 2.3 LLM 响应模型

```python
# context/models.py
@dataclass
class ChatResponse:
    """统一 LLM 响应格式（跨所有 provider）。"""
    content: str
    tool_calls: list[ToolCall] | None = None
    reasoning_content: str | None = None
    provider: ProviderInfo | None = None
    finish_reason: FinishReason = FinishReason.STOP
    usage: UsageInfo | None = None
```

### 2.4 Agent 响应与停止原因

```python
# agent/models.py
class StopReason(str, Enum):
    COMPLETED = "completed"              # 无工具调用，直接完成
    MAX_TURNS = "max_turns"              # 达到轮次上限
    LOOP_DETECTED = "loop_detected"      # 循环检测
    REPEATED_TOOL = "repeated_tool"      # 重复相同工具调用
    ERROR = "error"                      # 不可恢复错误
    USER_ABORTED = "user_aborted"        # 用户中断
    APPROVAL_DENIED = "approval_denied"  # 工具审批被拒
    APPROVAL_TIMEOUT = "approval_timeout"
    USER_INPUT_NEEDED = "user_input_needed"

@dataclass
class AgentResponse:
    """Agent 执行结果。"""
    content: str
    events: list[AgentEvent] = field(default_factory=list)
    stop_reason: StopReason = StopReason.COMPLETED
    message_trace: list[Message] = field(default_factory=list)  # 本轮产生的完整消息轨迹
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 2.5 事件模型

```python
# agent/models.py — 事件类型
class EventType(str, Enum):
    THINKING = "thinking"                # 思考中
    DELTA = "delta"                      # 流式文本增量
    TOOL_CALL_REQUEST = "tool_call_request"    # 请求工具审批
    TOOL_CALL_APPROVED = "tool_call_approved"  # 工具审批通过
    TOOL_CALL_DENIED = "tool_call_denied"      # 工具审批拒绝
    TOOL_EXECUTING = "tool_executing"    # 工具执行中
    TOOL_RESULT = "tool_result"          # 工具执行结果
    COMPLETE = "complete"                # 执行完成
    ERROR = "error"                      # 错误
    ABORTED = "aborted"                  # 用户中止

@dataclass
class AgentEvent:
    type: EventType
    timestamp: float
    data: dict[str, Any] = field(default_factory=dict)
```

---

## 3. MindAgent — 监督者入口

`MindAgent` 是用户直接交互的入口，管理主代理和子代理：

```python
# agent/core.py
class MindAgent:
    """MindBot supervisor agent."""

    def __init__(self, config: Config, capability_facade=None) -> None:
        self.config = config
        self._main_agent: Agent = self._build_main_agent(config, capability_facade)
        self._child_agents: dict[str, Agent] = {}  # 子代理注册表

        # Session Journal（可选的 append-only 持久化）
        self._journal: SessionJournal | None = None
        if config.session_journal.enabled:
            self._journal = SessionJournal(config.session_journal.path)
```

### chat() 流程

```python
# agent/core.py
async def chat(
    self, message: str, session_id: str = "default",
    on_event: Callable[[AgentEvent], None] | None = None,
    tools: list[Any] | None = None,
) -> AgentResponse:
    # 1. 委托给主 Agent 执行
    response = await self._main_agent.chat(
        message=message, session_id=session_id,
        on_event=on_event, tools=tools,
    )

    # 2. 写入 Session Journal
    self._write_journal(
        session_id, user_message=message,
        assistant_content=response.content or "",
        trace=response.message_trace or None,
    )

    return response
```

MindAgent 的角色很薄，主要是：
- **委托**：将实际执行委托给 `_main_agent`
- **日志**：写入 Session Journal
- **代理管理**：维护子代理注册表（多代理场景）

---

## 4. Agent — 独立代理

### 4.1 核心结构

```python
# agent/agent.py
class Agent:
    def __init__(self, name, llm, tools=None, system_prompt="",
                 context_config=None, memory=None, max_iterations=20,
                 max_sessions=1000, ...) -> None:
        self.name = name
        self.llm = llm                           # ProviderAdapter
        self.system_prompt = system_prompt
        self.memory = memory                      # MemoryManager（可选）
        self._max_iterations = max_iterations     # 最大工具轮次
        self._max_sessions = max_sessions         # LRU 会话缓存大小

        self.tool_registry = ToolRegistry()       # 工具注册表

        # 按 session 缓存（LRU via OrderedDict）
        self._sessions: OrderedDict[str, ContextManager] = OrderedDict()
        self._turn_engines: OrderedDict[str, TurnEngine] = OrderedDict()
        self._turn_engine_tool_signatures: dict[str, tuple] = {}
```

### 4.2 LRU 会话管理

```python
# agent/agent.py — LRU 会话缓存
def _get_session_context(self, session_id: str) -> ContextManager:
    if session_id in self._sessions:
        self._sessions.move_to_end(session_id)  # 移到 LRU 末尾
        return self._sessions[session_id]

    ctx = ContextManager(self._context_config)
    self._sessions[session_id] = ctx

    # 超过上限时驱逐最久未用的 session
    if len(self._sessions) > self._max_sessions:
        evicted = next(iter(self._sessions))
        self._sessions.pop(evicted)
        self._turn_engines.pop(evicted, None)
        self._turn_engine_tool_signatures.pop(evicted, None)

    return ctx
```

### 4.3 TurnEngine 缓存与失效

```python
# agent/agent.py — TurnEngine 缓存（基于工具签名失效）
def _get_turn_engine(self, session_id: str, turn_context) -> TurnEngine:
    tool_signature = (
        turn_context.tools_override_active,
        self._get_tool_signature(turn_context.tools),  # frozenset[(name, id)]
    )
    cached_sig = self._turn_engine_tool_signatures.get(session_id)

    # 工具变化时重建 TurnEngine
    if session_id not in self._turn_engines or cached_sig != tool_signature:
        turn_engine = TurnEngine(
            llm=self.llm,
            tools=turn_context.tools,
            max_iterations=self._max_iterations,
            capability_facade=turn_context.capability_facade,
        )
        self._turn_engines[session_id] = turn_engine
        self._turn_engine_tool_signatures[session_id] = tool_signature
    else:
        self._turn_engines.move_to_end(session_id)

    return self._turn_engines[session_id]
```

### 4.4 _run_turn — 共享执行路径

```python
# agent/agent.py
async def _run_turn(self, *, message, session_id, turn_context, on_event=None):
    # 1. 构建输入
    input_builder = self._get_session_input_builder(session_id)
    messages = input_builder.build(message, session_id=session_id)

    # 2. 执行对话循环
    turn_engine = self._get_turn_engine(session_id, turn_context)
    response = await turn_engine.run(messages=messages, on_event=on_event)

    # 3. 持久化
    writer = self._get_persistence_writer(session_id)
    writer.commit_turn(message, response, session_id=session_id)

    return response
```

---

## 5. TurnEngine — 核心对话循环

### 5.1 整体结构

TurnEngine 是 MindBot 的核心引擎，使用 `for iteration in range(max_iterations)` 循环：

```
TurnEngine.run(messages)
│
├── for iteration in range(max_iterations):     ← 默认 20 轮
│   │
│   ├── _execute_iteration()
│   │   ├── StreamingExecutor.execute_stream()  ← LLM 调用
│   │   │
│   │   ├── 无 tool_calls?
│   │   │   └── stop_reason = COMPLETED → return False（结束）
│   │   │
│   │   ├── 有 tool_calls:
│   │   │   ├── messages.append(assistant + tool_calls)
│   │   │   ├── _execute_tool_calls()           ← 工具执行
│   │   │   ├── messages.append(tool results)
│   │   │   ├── _has_repeated_tool_call()?      ← 重复检测
│   │   │   │   └── YES → stop_reason = REPEATED_TOOL → return False
│   │   │   └── return True（继续下一轮）
│   │   │
│   └── should_continue? → NO → break
│
├── for-else: stop_reason = MAX_TURNS          ← 循环正常结束
│
└── response.message_trace = messages[initial_len:]
```

### 5.2 run() 主方法

```python
# agent/turn_engine.py
class TurnEngine:
    def __init__(self, llm, tools=None, *, max_iterations=20,
                 capability_facade=None):
        self._llm = llm
        self._tools = tools or []
        self._max_iterations = max_iterations
        self._capability_facade = capability_facade
        self._streaming_executor = StreamingExecutor(llm)

    async def run(self, messages, on_event=None, turn_id=None) -> AgentResponse:
        response = AgentResponse(content="")
        initial_len = len(messages)

        try:
            for iteration in range(self._max_iterations):
                should_continue, messages = await self._execute_iteration(
                    messages=messages, iteration=iteration,
                    on_event=on_event, response=response, turn_id=turn_id,
                )
                if not should_continue:
                    break
            else:
                # for-else: 循环正常结束（未 break）→ 达到最大轮次
                response.stop_reason = StopReason.MAX_TURNS
                if on_event:
                    on_event(AgentEvent.complete(response.stop_reason))

            if on_event and response.stop_reason == StopReason.COMPLETED:
                on_event(AgentEvent.complete(response.stop_reason))

        except Exception as exc:
            response.stop_reason = StopReason.ERROR
            if on_event:
                on_event(AgentEvent.error(str(exc)))

        # 构建消息轨迹（本轮产生的所有消息）
        trace = messages[initial_len:]
        if response.stop_reason == StopReason.COMPLETED and response.content:
            has_final_assistant = (
                trace and trace[-1].role == "assistant" and not trace[-1].tool_calls
            )
            if not has_final_assistant:
                final_msg = Message(role="assistant", content=response.content)
                messages.append(final_msg)
                trace = messages[initial_len:]

        response.message_trace = trace
        return response
```

### 5.3 _execute_iteration — 单次迭代

```python
# agent/turn_engine.py
async def _execute_iteration(
    self, messages, iteration, on_event, response, turn_id=None,
) -> tuple[bool, list[Message]]:
    """执行一次 LLM 调用 + 可选的工具执行。返回 (should_continue, updated_messages)"""

    # 1. 调用 LLM
    llm_response = await self._streaming_executor.execute_stream(
        messages=messages, on_event=on_event, tools=self._tools,
    )

    # 2. 累计文本内容
    if llm_response.content:
        response.content += llm_response.content

    # 3. 检查工具调用
    tool_calls = llm_response.tool_calls
    if not tool_calls:
        response.stop_reason = StopReason.COMPLETED
        return False, messages  # ← 不继续，对话完成

    # 4. 记录 assistant 消息（含 tool_calls + reasoning_content）
    messages.append(Message(
        role="assistant",
        content=llm_response.content or "",
        tool_calls=tool_calls,
        reasoning_content=llm_response.reasoning_content,
    ))

    # 5. 执行工具调用
    tool_results = await self._execute_tool_calls(
        tool_calls=tool_calls, on_event=on_event, turn_id=turn_id,
    )

    # 6. 记录工具结果
    for tr in tool_results:
        messages.append(Message(
            role="tool",
            content=tr.content if tr.success else f"Error: {tr.error}",
            tool_call_id=tr.tool_call_id,
        ))

    # 7. 重复工具调用检测
    if self._has_repeated_tool_call(messages, tool_calls, iteration):
        response.stop_reason = StopReason.REPEATED_TOOL
        return False, messages

    return True, messages  # ← 继续，进入下一轮
```

### 5.4 重复工具调用检测

```python
# agent/turn_engine.py
@staticmethod
def _has_repeated_tool_call(messages, tool_calls, iteration) -> bool:
    """检测连续两次完全相同的工具调用（名称 + 参数）。"""
    if iteration < 1 or not tool_calls:
        return False

    # 从后往前找到前一次 assistant+tool_calls 消息
    latest_previous = None
    seen_current_assistant = False
    for msg in reversed(messages):
        if msg.role != "assistant" or not msg.tool_calls:
            continue
        if not seen_current_assistant:
            seen_current_assistant = True  # 跳过当前轮
            continue
        latest_previous = msg.tool_calls
        break

    if latest_previous is None:
        return False
    if len(latest_previous) != len(tool_calls):
        return False

    # 逐一比较工具名称和参数
    for previous, current in zip(latest_previous, tool_calls):
        if previous.name != current.name or previous.arguments != current.arguments:
            return False

    return True  # 完全相同 → 重复
```

---

## 6. InputBuilder — 消息组装

### 6.1 职责

`InputBuilder` 负责每轮对话的 LLM 输入组装，从 ContextManager 的各 Block 中读取消息：

```
InputBuilder.build(user_input)
│
├── 1. _populate_skills_blocks(query)     → 选择并渲染技能
├── 2. _populate_memory_block(query)      → 检索相关记忆
├── 3. _ctx.set_intent_state(...)         → 设置意图状态
├── 4. _ctx.set_user_input(user_msg)      → 设置用户输入
│
└── 5. 按 Block 顺序拼接消息
    for block_name in ctx.block_names:
        assembled.extend(ctx.get_block_messages(block_name))
```

### 6.2 build() 方法

```python
# agent/input_builder.py
class InputBuilder:
    def build(self, user_input, *, session_id=None, intent_state=None) -> list[Message]:
        """构建一次 LLM 调用的完整消息列表。"""
        t0 = time.perf_counter()

        query_text = user_input if isinstance(user_input, str) else _extract_text(user_input)

        # 1. 技能块
        self._populate_skills_blocks(query_text)

        # 2. 记忆块
        self._populate_memory_block(query_text)

        # 3. 意图状态块
        self._ctx.set_intent_state(intent_state)

        # 4. 用户输入块
        user_msg = Message(role="user", content=user_input)
        user_msg.token_count = estimate_tokens(user_msg.text)
        self._ctx.set_user_input(user_msg)

        # 5. 按 Block 顺序拼接
        assembled: list[Message] = []
        for block_name in self._ctx.block_names:
            assembled.extend(self._ctx.get_block_messages(block_name))

        return assembled
```

### 6.3 记忆检索

```python
# agent/input_builder.py
def _populate_memory_block(self, query: str) -> None:
    """检索相关记忆并填充 memory block。"""
    if self._memory is None:
        self._ctx.set_memory_messages([])
        return

    chunks = []
    try:
        chunks = self._memory.search(query, top_k=self._memory_top_k)
    except Exception:
        logger.debug("Memory search failed; continuing without memories")

    if not chunks:
        self._ctx.set_memory_messages([])
        return

    ctx_text = "\n".join(f"- {c.text}" for c in chunks)
    memory_msg = Message(role="system", content=f"Relevant context from memory:\n{ctx_text}")
    memory_msg.token_count = estimate_tokens(memory_msg.text)
    self._ctx.set_memory_messages([memory_msg])
```

---

## 7. ContextManager — Block 分区上下文管理

### 7.1 Block 分区设计

ContextManager 将上下文窗口分为 **7 个 Block**，每个 Block 有独立的 token 预算：

```python
# context/manager.py
_DEFAULT_RATIOS = {
    "system_identity": 0.12,   # 系统提示词 / 角色定义
    "skills_overview": 0.08,   # 始终可见的技能概览
    "skills_detail":  0.15,   # 当前轮选中的技能详情
    "memory":         0.15,   # 检索到的记忆片段
    "conversation":   0.35,   # 对话历史（最大，可被压缩）
    "intent_state":   0.05,   # 意图/上下文提示
    "user_input":     0.10,   # 当前用户输入
}

@dataclass
class ContextBlock:
    name: str
    max_tokens: int
    messages: list[Message] = field(default_factory=list)

    @property
    def token_count(self) -> int:
        return sum(m.token_count for m in self.messages)

    @property
    def remaining(self) -> int:
        return max(0, self.max_tokens - self.token_count)
```

### 7.2 消息组装顺序

```
┌──────────────────────────┐
│ system_identity (12%)    │  ← 系统提示词
├──────────────────────────┤
│ skills_overview (8%)     │  ← 技能概览
├──────────────────────────┤
│ skills_detail (15%)      │  ← 技能详情（轮级别）
├──────────────────────────┤
│ memory (15%)             │  ← 检索记忆（轮级别）
├──────────────────────────┤
│ conversation (35%)       │  ← 对话历史（跨轮累积）
├──────────────────────────┤
│ intent_state (5%)        │  ← 意图提示（轮级别）
├──────────────────────────┤
│ user_input (10%)         │  ← 用户输入（轮级别）
└──────────────────────────┘
```

### 7.3 自动压缩触发

```python
# context/manager.py
def add_conversation_message(self, role, content, **kwargs) -> Message:
    msg = Message(role=role, content=content, **kwargs)
    msg.token_count = estimate_tokens(msg.text)
    self._blocks["conversation"].messages.append(msg)
    self._check_and_compact()  # ← 每次添加后检查
    return msg

def _check_and_compact(self) -> None:
    conv = self._blocks["conversation"]
    if conv.token_count > conv.max_tokens:
        logger.info(
            "Conversation block budget exceeded (%d > %d) – compacting",
            conv.token_count, conv.max_tokens,
        )
        self.compact()

def compact(self) -> None:
    conv = self._blocks["conversation"]
    conv.messages = self._strategy.compress(conv.messages, conv.max_tokens)
    for m in conv.messages:
        m.token_count = estimate_tokens(m.text)
```

### 7.4 Checkpoint 机制

```python
# context/manager.py
def create_checkpoint(self, name="") -> str:
    """快照所有 Block；返回 checkpoint ID。"""
    cid = uuid.uuid4().hex
    snapshot = {
        bname: list(block.messages) for bname, block in self._blocks.items()
    }
    self._checkpoints[cid] = Checkpoint(id=cid, name=name, messages=self.messages)
    self._checkpoints[cid]._block_snapshot = snapshot
    return cid

def rollback_to_checkpoint(self, checkpoint_id) -> None:
    """从 checkpoint 恢复所有 Block 内容。"""
    cp = self._checkpoints.get(checkpoint_id)
    snapshot = getattr(cp, "_block_snapshot", {})
    if snapshot:
        for bname, msgs in snapshot.items():
            if bname in self._blocks:
                self._blocks[bname].messages = list(msgs)
```

---

## 8. 压缩策略

MindBot 内置了 **6 种压缩策略**，均为 `CompressionStrategy` 抽象类的实现：

### 8.1 策略继承体系

```
CompressionStrategy (ABC)
├── TruncateStrategy      — 截断最旧消息（默认）
├── SummarizeStrategy     — LLM 摘要压缩
├── ExtractStrategy       — 提取关键信息
├── MixStrategy           — 摘要 + 提取混合
└── ArchiveStrategy       — 归档到记忆系统
```

### 8.2 TruncateStrategy — 默认截断

```python
# context/compression.py
class TruncateStrategy(CompressionStrategy):
    """从最旧的非系统消息开始丢弃，直到满足 token 预算。"""

    def compress(self, messages, target_tokens) -> list[Message]:
        system = [m for m in messages if m.role == "system"]
        others = [m for m in messages if m.role != "system"]

        total = sum(estimate_tokens(m.text) for m in system)
        keep: list[Message] = []

        # 从最新消息开始保留
        for msg in reversed(others):
            cost = estimate_tokens(msg.text)
            if total + cost > target_tokens:
                break
            keep.append(msg)
            total += cost

        keep.reverse()
        return system + keep
```

### 8.3 SummarizeStrategy — LLM 摘要

```python
# context/compression.py
class SummarizeStrategy(CompressionStrategy):
    """用 LLM 摘要旧消息，保留最近几条原文。"""

    def __init__(self, llm, recent_keep=4):
        self._llm = llm
        self._recent_keep = recent_keep

    def compress(self, messages, target_tokens) -> list[Message]:
        if len(messages) <= self._recent_keep + 1:
            return list(messages)

        system = [m for m in messages if m.role == "system"]
        non_system = [m for m in messages if m.role != "system"]

        to_summarize = non_system[:-self._recent_keep]
        to_keep = non_system[-self._recent_keep:]

        # 调用 LLM 生成摘要
        text_block = "\n".join(f"[{m.role}]: {m.text}" for m in to_summarize)
        summary_prompt = (
            "Summarize the following conversation concisely, preserving key "
            "facts, decisions, and tool results:\n\n" + text_block
        )
        try:
            response = run_sync(self._llm.chat([Message(role="user", content=summary_prompt)]))
            summary_msg = Message(
                role="system",
                content=f"[Conversation summary] {response.content}",
            )
        except Exception:
            # 摘要失败 → 回退到截断
            return TruncateStrategy().compress(messages, target_tokens)

        return system + [summary_msg] + to_keep
```

### 8.4 策略工厂

```python
# context/compression.py
def get_strategy(name, **kwargs) -> CompressionStrategy:
    """按名称返回压缩策略。"""
    if name == "truncate":  return TruncateStrategy()
    if name == "summarize": return SummarizeStrategy(kwargs["llm"])
    if name == "extract":   return ExtractStrategy(kwargs["llm"])
    if name == "mix":       return MixStrategy(kwargs["llm"])
    if name == "archive":   return ArchiveStrategy(kwargs["memory"])
    raise ValueError(f"Unknown compression strategy: {name!r}")
```

---

## 9. 工具执行路径

### 9.1 StreamingExecutor — LLM 调用适配

```python
# agent/streaming.py
class StreamingExecutor:
    """Provider-level streaming adapter.

    - 无工具时：流式调用 LLM
    - 有工具时：非流式调用（需要完整响应来解析 tool_calls）
    """

    async def execute_stream(self, messages, on_event=None, tools=None, **llm_kwargs):
        if on_event:
            on_event(AgentEvent.thinking())

        if tools:
            # 有工具 → 非流式（大多数 provider 需要完整响应解析 tool_calls）
            return await self._execute_with_tools(messages, on_event, tools, **llm_kwargs)

        # 无工具 → 流式
        return await self._execute_stream_only(messages, on_event, **llm_kwargs)

    async def _execute_with_tools(self, messages, on_event, tools, **llm_kwargs):
        response = await self._llm.chat(messages, tools=tools, **llm_kwargs)
        if on_event and response.content:
            on_event(AgentEvent.delta(response.content))
        return response

    async def _execute_stream_only(self, messages, on_event, **llm_kwargs):
        content_parts = []
        async for chunk in self._llm.chat_stream(messages, **llm_kwargs):
            if chunk:
                content_parts.append(chunk)
                if on_event:
                    on_event(AgentEvent.delta(chunk))
        return ChatResponse(content="".join(content_parts), tool_calls=None)
```

### 9.2 工具执行流 — CapabilityFacade

TurnEngine 中的工具执行统一通过 `CapabilityFacade` 调度：

```python
# agent/turn_engine.py
async def _execute_tool_calls(self, tool_calls, on_event, turn_id=None):
    """逐个执行工具调用（串行）。"""
    results = []
    for tool_call in tool_calls:
        try:
            if on_event:
                on_event(AgentEvent.tool_executing(
                    tool_name=tool_call.name, call_id=tool_call.id
                ))

            # 通过 CapabilityFacade 解析并执行
            tool_result = await self._resolve_and_execute(tool_call, turn_id)
            results.append(tool_result)

            if on_event:
                on_event(AgentEvent.tool_result(
                    tool_name=tool_call.name, call_id=tool_call.id,
                    result=tool_result.content if tool_result.success else tool_result.error,
                ))

        except Exception as exc:
            results.append(ToolResult(
                tool_call_id=tool_call.id, success=False, error=str(exc)
            ))
    return results

async def _resolve_and_execute(self, tool_call, turn_id):
    """工具执行的唯一调度点。"""
    content = await self._capability_facade.resolve_and_execute(
        CapabilityQuery(name=tool_call.name, capability_type=CapabilityType.TOOL),
        arguments=tool_call.arguments,
        context={"tool_call_id": tool_call.id, "turn_id": turn_id},
    )
    return ToolResult(tool_call_id=tool_call.id, success=True, content=content)
```

### 9.3 CapabilityFacade 简述

```python
# capability/facade.py
class CapabilityFacade:
    """统一的能力 API（Resolve + Execute）。"""

    def __init__(self):
        self._executor = CapabilityExecutor()
        self._registry = CapabilityRegistry()

    async def resolve_and_execute(self, query, arguments=None, context=None):
        """一步完成：解析能力 → 执行。"""
        cap = self._registry.resolve(query)
        return await self._executor.execute(cap.id, arguments, context)
```

---

## 10. 持久化写入

`PersistenceWriter` 统一了三种持久化目标：

```python
# agent/persistence_writer.py
class PersistenceWriter:
    def commit_turn(self, user_text, response, *, session_id="default"):
        """一次 turn 完成后的统一持久化入口。"""
        assistant_text = response.content or ""
        trace = response.message_trace or []

        self._commit_conversation(user_text, assistant_text, trace)
        self._commit_memory(user_text, assistant_text)
        self._commit_journal(user_text, assistant_text, trace, session_id)
```

### 10.1 会话上下文持久化

```python
# agent/persistence_writer.py
def _commit_conversation(self, user_text, assistant_text, trace):
    """写入 conversation block。"""
    self._ctx.add_conversation_message("user", user_text)

    # 根据 tool_persistence 策略处理工具消息
    if trace:
        self._persist_tool_messages(trace)

    self._ctx.add_conversation_message("assistant", assistant_text)
    self._ctx.clear_user_input()
    self._ctx.clear_intent_state()

def _persist_tool_messages(self, messages):
    if self._tool_persistence == "none":
        return  # 不保留工具消息

    if self._tool_persistence == "full":
        # 完整保留所有中间消息
        for msg in messages:
            if msg.role != "system":
                self._ctx.add_conversation(msg)
        return

    # "summary" — 摘要为一条 system 消息
    tool_names = []
    for msg in messages:
        if msg.role == "assistant" and msg.tool_calls:
            tool_names.extend(tc.name for tc in msg.tool_calls)
    if tool_names:
        summary_msg = Message(role="system",
                              content=f"[Tool usage summary] Called: {', '.join(tool_names)}")
        self._ctx.add_conversation(summary_msg)
```

### 10.2 三种 tool_persistence 策略

| 策略 | 行为 | Token 消耗 |
|------|------|-----------|
| `none` | 不保留任何工具中间消息 | 最低 |
| `summary` | 压缩为一条 `[Tool usage summary]` 系统消息 | 低 |
| `full` | 保留所有 assistant+tool_calls 和 tool result 消息 | 最高 |

---

## 11. 完整调用链路图

一个完整的 `MindAgent.chat("hello")` 调用，涉及所有组件的数据流：

```
用户: "hello"
│
├── MindAgent.chat("hello", session_id="default")
│   │
│   └── Agent.chat("hello", session_id="default")
│       │
│       ├── _build_turn_context(tools=None)
│       │   ├── list_tools() → [Tool(...), Tool(...), ...]
│       │   └── build_turn_scoped_facade(...) → ScopedCapabilityFacade
│       │
│       └── _run_turn(message="hello", session_id="default")
│           │
│           ├── InputBuilder.build("hello")
│           │   ├── _populate_skills_blocks("hello")
│           │   │   ├── SkillSelector.select("hello") → matched skills
│           │   │   ├── render_skills_overview() → 概览文本
│           │   │   └── render_skills_detail() → 详情文本
│           │   │
│           │   ├── _populate_memory_block("hello")
│           │   │   └── memory.search("hello", top_k=5) → [MemoryChunk, ...]
│           │   │
│           │   ├── ctx.set_intent_state(None)  → 空
│           │   ├── ctx.set_user_input(Message("hello"))
│           │   │
│           │   └── 按 Block 顺序拼接:
│           │       [system_identity] → "You are MindBot..."
│           │       [skills_overview] → "Available skills: ..."
│           │       [skills_detail]  → (可选)
│           │       [memory]         → "Relevant context from memory: ..."
│           │       [conversation]   → [历史 user/assistant 消息]
│           │       [intent_state]   → (可选)
│           │       [user_input]     → "hello"
│           │
│           │       = 最终 list[Message] 发给 LLM
│           │
│           ├── TurnEngine.run(messages)
│           │   │
│           │   ├── iteration 0:
│           │   │   ├── StreamingExecutor.execute_stream(messages, tools=[...])
│           │   │   │   └── _execute_with_tools() → ChatResponse
│           │   │   │       ├── content: "Let me search for..."
│           │   │   │       └── tool_calls: [ToolCall("web_search", {...})]
│           │   │   │
│           │   │   ├── messages.append(assistant + tool_calls)
│           │   │   ├── _execute_tool_calls([ToolCall])
│           │   │   │   └── facade.resolve_and_execute("web_search", {...})
│           │   │   │       → "Search results: ..."
│           │   │   ├── messages.append(tool result)
│           │   │   └── return True → 继续
│           │   │
│           │   ├── iteration 1:
│           │   │   ├── StreamingExecutor.execute_stream(messages, tools=[...])
│           │   │   │   └── ChatResponse(content="Based on the search...", tool_calls=None)
│           │   │   └── return False → COMPLETED
│           │   │
│           │   └── response.message_trace = messages[initial_len:]
│           │
│           └── PersistenceWriter.commit_turn("hello", response)
│               ├── _commit_conversation()
│               │   ├── ctx.add_conversation_message("user", "hello")
│               │   ├── _persist_tool_messages(trace)  → summary/none/full
│               │   └── ctx.add_conversation_message("assistant", "Based on...")
│               │
│               ├── _commit_memory("hello", "Based on...")
│               │   ├── memory.append_to_short_term("User: hello")
│               │   └── memory.append_to_short_term("Assistant: Based on...")
│               │
│               └── _commit_journal("hello", "Based on...", trace, "default")
│                   └── journal.append("default", [SessionMessage, ...])
│
└── MindAgent._write_journal(session_id, "hello", response.content, trace)
    └── journal.append(...)  ← 补充 Journal（如有）
```

---

## 12. 与 Claude Code 的对比与改进方向

### 12.1 架构对比

| 维度 | Claude Code | MindBot |
|------|-------------|---------|
| **循环模式** | `while(true) + state = next + continue` | `for iteration in range(max_iterations)` |
| **状态传递** | 7 字段 State 对象，原子替换 | 直接 mutate messages 列表 |
| **上下文管理** | 扁平消息数组 + 多层压缩管道 | Block 分区 + 独立 token 预算 |
| **压缩策略** | 4 层管道（snip→microcompact→collapse→autocompact） | 可插拔策略（truncate/summarize/extract/mix/archive） |
| **工具执行** | 并发安全分区 + 流式执行 | 串行逐个执行 |
| **流式集成** | 有工具时仍可流式（StreamingToolExecutor） | 有工具时退化为非流式 |
| **错误恢复** | withhold-and-recover（隐藏→恢复→展示） | 直接抛异常，无自动恢复 |
| **持久化** | JSONL transcript，细粒度 fire-and-forget | PersistenceWriter 统一提交 |
| **消息类型** | 10+ 种联合类型 | 4 种 role |
| **工具发现** | ToolSearchTool 延迟加载 | SkillSelector 按查询匹配 |

### 12.2 MindBot 的优势

1. **Block 分区** — token 预算按 Block 分配，比扁平消息数组更可控，保证各类型信息都有空间
2. **可插拔压缩** — 6 种策略可按场景选择，且支持优雅降级（摘要失败→截断）
3. **Checkpoint** — 支持上下文快照和回滚
4. **tool_persistence** — 三级策略（none/summary/full）平衡 token 消耗与上下文完整性
5. **LRU 会话缓存** — 自动管理内存，适合多会话场景

### 12.3 可改进的方向

**1. 循环模式升级**

当前 `for range` 模式不支持压缩后重试、错误恢复等场景。建议引入 `while(true) + transition` 模式：

```python
# 建议改进
while True:
    result = await self._execute_iteration(...)

    if result.transition == "next_turn":
        state = result.next_state
        continue  # 正常下一轮
    elif result.transition == "compact_retry":
        # 压缩后重试同一轮
        messages = result.compacted_messages
        continue
    elif result.transition == "completed":
        break
```

**2. 工具并发执行**

当前工具串行执行。对于只读工具（如 search、read），可以并行：

```python
# 建议改进
async def _execute_tool_calls(self, tool_calls, ...):
    safe_calls, unsafe_calls = self._partition_by_safety(tool_calls)

    # 只读工具并行
    safe_results = await asyncio.gather(*[
        self._resolve_and_execute(tc, turn_id) for tc in safe_calls
    ])

    # 写操作工具串行
    unsafe_results = []
    for tc in unsafe_calls:
        result = await self._resolve_and_execute(tc, turn_id)
        unsafe_results.append(result)

    return safe_results + unsafe_results
```

**3. 流式工具执行**

StreamingExecutor 在有工具时退化为非流式。可以改为流式输出中提前识别 tool_use 块并开始执行：

```python
# 建议改进：流式识别 + 早期执行
async def execute_stream_with_early_tools(self, messages, tools, ...):
    async for event in self._llm.chat_stream_with_tools(messages, tools=tools):
        if event.type == "tool_use_start":
            # 立即开始执行（不等流结束）
            asyncio.create_task(self._execute_tool_early(event.tool_call))
        yield event
```

**4. 错误恢复机制**

建议增加 prompt-too-long 和 max-output-tokens 的自动恢复：

```python
# 建议改进：错误恢复
async def _execute_iteration(self, ...):
    try:
        llm_response = await self._streaming_executor.execute_stream(...)
    except PromptTooLongError:
        # 自动压缩后重试
        self._ctx.compact()
        llm_response = await self._streaming_executor.execute_stream(...)
    except MaxOutputTokensError:
        # 注入 "继续" 消息后重试
        messages.append(Message(role="user", content="Continue from where you left off."))
        llm_response = await self._streaming_executor.execute_stream(...)
```

**5. 消息轨迹增强**

当前 `message_trace` 只有基础 role/content。建议增加更丰富的元数据：

```python
# 建议改进
@dataclass
class Message:
    role: MessageRole
    content: MessageContent
    # ... 现有字段 ...

    # 建议新增
    parent_tool_use_id: str | None = None   # 子代理/嵌套工具调用
    stop_reason: str | None = None          # 此消息对应的 API stop_reason
    usage: UsageInfo | None = None          # token 使用统计
    is_meta: bool = False                   # 系统注入的元消息（如恢复提示）
```

---

*文档生成时间: 2026-04-08*
*分析源码版本: MindBot v0.3.x*
