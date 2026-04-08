---
title: 枚举类型
---

# 枚举类型

MindBot 使用字符串枚举（`str, Enum`）确保序列化和类型安全。所有枚举值均可作为字符串直接比较。

---

## StopReason

**模块**：`mindbot.agent.models`

Agent 循环终止原因，描述对话为何结束。

| 枚举值 | 字符串值 | 说明 |
|--------|----------|------|
| `COMPLETED` | `"completed"` | LLM 返回了文本且未请求工具调用，正常完成 |
| `MAX_TURNS` | `"max_turns"` | 达到最大轮次限制 |
| `LOOP_DETECTED` | `"loop_detected"` | 检测到重复相同的工具调用循环 |
| `REPEATED_TOOL` | `"repeated_tool"` | 相同工具 + 相同参数出现了两次 |
| `ERROR` | `"error"` | 不可恢复的错误 |
| `USER_ABORTED` | `"user_aborted"` | 用户中断执行 |
| `APPROVAL_DENIED` | `"approval_denied"` | 工具调用审批被拒绝 |
| `APPROVAL_TIMEOUT` | `"approval_timeout"` | 工具调用审批超时 |
| `USER_INPUT_NEEDED` | `"user_input_needed"` | 等待用户输入 |

**使用示例**：

```python
from mindbot.agent.models import AgentResponse, StopReason

response: AgentResponse = await bot.chat("...")

if response.stop_reason == StopReason.COMPLETED:
    print("正常完成")
elif response.stop_reason == StopReason.MAX_TURNS:
    print("达到最大轮次限制")
elif response.stop_reason == StopReason.ERROR:
    print("发生错误")
```

---

## EventType

**模块**：`mindbot.agent.models`

Agent 执行过程中发出的事件类型。

| 枚举值 | 字符串值 | 说明 |
|--------|----------|------|
| `THINKING` | `"thinking"` | Agent 正在思考 |
| `DELTA` | `"delta"` | 流式内容增量 |
| `TOOL_CALL_REQUEST` | `"tool_call_request"` | 请求工具调用审批 |
| `TOOL_CALL_APPROVED` | `"tool_call_approved"` | 工具调用已批准 |
| `TOOL_CALL_DENIED` | `"tool_call_denied"` | 工具调用被拒绝 |
| `TOOL_EXECUTING` | `"tool_executing"` | 正在执行工具 |
| `TOOL_RESULT` | `"tool_result"` | 工具执行结果 |
| `USER_INPUT_REQUEST` | `"user_input_request"` | 请求用户输入 |
| `USER_INPUT_RECEIVED` | `"user_input_received"` | 收到用户输入 |
| `COMPLETE` | `"complete"` | 执行完成 |
| `ERROR` | `"error"` | 发生错误 |
| `ABORTED` | `"aborted"` | 执行被用户中止 |

**使用示例**：

```python
from mindbot.agent.models import EventType

def on_event(event):
    match event.type:
        case EventType.THINKING:
            print("思考中...")
        case EventType.DELTA:
            print(event.data["content"], end="")
        case EventType.TOOL_EXECUTING:
            print(f"执行工具: {event.data['tool_name']}")
        case EventType.COMPLETE:
            print(f"完成: {event.data['stop_reason']}")
        case EventType.ERROR:
            print(f"错误: {event.data['message']}")

response = await bot.chat("...", on_event=on_event)
```

---

## FinishReason

**模块**：`mindbot.context.models`

LLM 生成停止原因，描述模型为何停止生成 Token。

| 枚举值 | 字符串值 | 说明 |
|--------|----------|------|
| `STOP` | `"stop"` | 自然结束（遇到停止符） |
| `TOOL_CALLS` | `"tool_calls"` | 模型请求调用工具 |
| `LENGTH` | `"length"` | 达到最大 Token 长度限制 |
| `ERROR` | `"error"` | 生成过程中出错 |

---

## MessageRole

**模块**：`mindbot.context.models`

消息角色类型（`Literal` 类型别名，非 Enum 类）。

```python
MessageRole = Literal["system", "user", "assistant", "tool"]
```

| 值 | 说明 |
|----|------|
| `"system"` | 系统消息，包含指令、人格设定和上下文信息 |
| `"user"` | 用户消息 |
| `"assistant"` | 助手回复消息 |
| `"tool"` | 工具执行结果消息，需配合 `tool_call_id` 使用 |

---

## MessageKind

**模块**：`mindbot.context.models`

消息分类标记（`Literal` 类型别名，非 Enum 类），用于持久化、可观测性和恢复流程。

```python
MessageKind = Literal[
    "assistant_text",
    "assistant_tool_call",
    "tool_result",
    "system_injected",
    "recovery_prompt",
]
```

| 值 | 说明 |
|----|------|
| `"assistant_text"` | 助手的纯文本回复 |
| `"assistant_tool_call"` | 助手的工具调用消息 |
| `"tool_result"` | 工具执行结果 |
| `"system_injected"` | 系统注入的消息（如摘要、压缩后内容） |
| `"recovery_prompt"` | 恢复流程的提示消息 |

---

## AgentDecision

**模块**：`mindbot.agent.models`

LLM 在 Agent 执行过程中做出的决策类型。

| 枚举值 | 字符串值 | 说明 |
|--------|----------|------|
| `CONTINUE` | `"continue"` | 继续思考/生成 |
| `TOOLS` | `"tools"` | 需要调用工具 |
| `USER_INPUT` | `"user_input"` | 需要用户输入 |
| `COMPLETE` | `"complete"` | 任务完成 |
| `ERROR` | `"error"` | 发生错误 |

---

## ApprovalDecision

**模块**：`mindbot.agent.models`

用户对工具调用审批的决策。

| 枚举值 | 字符串值 | 说明 |
|--------|----------|------|
| `ALLOW_ONCE` | `"allow_once"` | 本次允许执行 |
| `ALLOW_ALWAYS` | `"allow_always"` | 始终允许（加入白名单） |
| `DENY` | `"deny"` | 拒绝执行 |

---

## ToolSecurityLevel

**模块**：`mindbot.config.schema`

工具执行的安全级别。

| 枚举值 | 字符串值 | 说明 |
|--------|----------|------|
| `DENY` | `"deny"` | 默认拒绝所有工具 |
| `ALLOWLIST` | `"allowlist"` | 仅白名单中的工具允许执行 |
| `FULL` | `"full"` | 完全访问（需审批提示） |

---

## ToolAskMode

**模块**：`mindbot.config.schema`

何时向用户请求工具调用审批。

| 枚举值 | 字符串值 | 说明 |
|--------|----------|------|
| `OFF` | `"off"` | 从不请求审批 |
| `ON_MISS` | `"on_miss"` | 不在白名单时请求审批 |
| `ALWAYS` | `"always"` | 始终请求审批 |

---

## ToolPersistenceStrategy

**模块**：`mindbot.config.schema`

工具调用消息在每轮结束后的持久化策略。

| 枚举值 | 字符串值 | 说明 |
|--------|----------|------|
| `NONE` | `"none"` | 不持久化工具消息 |
| `SUMMARY` | `"summary"` | 持久化工具消息的摘要 |
| `FULL` | `"full"` | 完整持久化所有工具消息 |
