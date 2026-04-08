---
title: API 参考文档
---

# API 参考文档

本页面列出 MindBot 所有公开 API，按功能模块分类，每个模块均有独立子页面提供详细说明。

---

## 核心入口

| API | 模块 | 说明 |
|-----|------|------|
| [MindBot](mindbot.md) | `mindbot.bot` | 框架主入口类，封装配置加载、Agent 创建、内存管理和定时任务 |
| [MindAgent](agent.md#mindagent) | `mindbot.agent.core` | 监督者 Agent，管理主 Agent、子 Agent 注册表和会话日志 |
| [Agent](agent.md#agent) | `mindbot.agent.agent` | 自包含对话 Agent，提供会话管理、工具注册和上下文维护 |

---

## 对话接口

所有对话接口均支持异步调用，提供流式和非流式两种模式。

| 方法 | 所属类 | 说明 |
|------|--------|------|
| `chat()` | MindBot / MindAgent / Agent | 非流式对话，返回 `AgentResponse` |
| `chat_stream()` | MindBot / MindAgent / Agent | 流式对话，返回 `AsyncIterator[str]` |

---

## 响应与事件模型

| API | 模块 | 说明 |
|-----|------|------|
| [AgentResponse](models.md#agentresponse) | `mindbot.agent.models` | 对话响应结果，包含内容、事件列表和停止原因 |
| [AgentEvent](models.md#agentevent) | `mindbot.agent.models` | 执行过程中发出的事件，用于流式传输和监控 |
| [ChatResponse](models.md#chatresponse) | `mindbot.context.models` | LLM Provider 统一响应格式 |

---

## 消息模型

| API | 模块 | 说明 |
|-----|------|------|
| [Message](models.md#message) | `mindbot.context.models` | 统一多模态消息格式，支持文本和图像内容 |
| [ToolCall](models.md#toolcall) | `mindbot.context.models` | LLM 请求的工具调用 |
| [ToolResult](models.md#toolresult) | `mindbot.context.models` | 工具执行的返回结果 |
| [UsageInfo](models.md#usageinfo) | `mindbot.context.models` | Token 使用统计 |
| [ProviderInfo](models.md#providerinfo) | `mindbot.context.models` | Provider 元信息 |

---

## 枚举类型

| API | 模块 | 说明 |
|-----|------|------|
| [StopReason](enums.md#stopreason) | `mindbot.agent.models` | Agent 循环终止原因 |
| [EventType](enums.md#eventtype) | `mindbot.agent.models` | Agent 执行事件类型 |
| [FinishReason](enums.md#finishreason) | `mindbot.context.models` | LLM 生成停止原因 |
| [MessageRole](enums.md#messagerole) | `mindbot.context.models` | 消息角色类型 |
| [MessageKind](enums.md#messagekind) | `mindbot.context.models` | 消息分类标记 |
| [ApprovalDecision](enums.md#approvaldecision) | `mindbot.agent.models` | 用户审批决策 |
| [AgentDecision](enums.md#agentdecision) | `mindbot.agent.models` | LLM 决策类型 |
| [ToolPersistenceStrategy](enums.md#toolpersistencestrategy) | `mindbot.config.schema` | 工具消息持久化策略 |

---

## 上下文管理

| API | 模块 | 说明 |
|-----|------|------|
| [ContextManager](context.md#contextmanager) | `mindbot.context.manager` | 基于分区（Block）的上下文窗口管理，自动压缩和检查点 |
| [ContextBlock](context.md#contextblock) | `mindbot.context.manager` | 单个上下文分区，持有消息列表和 Token 预算 |
| [Checkpoint](context.md#checkpoint) | `mindbot.context.checkpoint` | 对话状态快照，支持回滚 |

### 压缩策略

| 策略 | 说明 |
|------|------|
| [TruncateStrategy](context.md#truncatestrategy) | 丢弃最早的非系统消息 |
| [SummarizeStrategy](context.md#summarizestrategy) | 通过 LLM 摘要旧消息 |
| [ExtractStrategy](context.md#extractstrategy) | 提取关键信息替换旧消息 |
| [MixStrategy](context.md#mixstrategy) | 摘要 + 提取混合策略 |
| [ArchiveStrategy](context.md#archivestrategy) | 将旧消息归档到内存系统 |
