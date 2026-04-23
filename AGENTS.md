# MindBot Development Guide for AI Agents

This guide helps AI agents assist in developing MindBot — a modular AI Agent framework built with Python + asyncio.

---

## FIRST: 确认上下文

**Before doing anything else:**

1. Read this file fully
2. Run `git status` to understand current branch and uncommitted changes
3. Read the relevant source files under `src/mindbot/` before modifying
4. Run existing tests: `pytest tests/ -m 'not integration' -q`

**Before writing code:**

- Read the target module and its tests first
- Check if your change bypasses `Agent.chat()` main chain (it must not)
- Verify imports follow the layer dependency: L1 → L2 → (L3, L4) → L5

---

## MindBot 五层架构

```text
┌─────────────────────────────────────────────────────────────────┐
│ L1 Interface / Transport                                        │
│  channels/*  bus/*  cli/*                                       │
│  Receive/dispatch messages; protocol adaptation                 │
│  Imports from: L2                                               │
├─────────────────────────────────────────────────────────────────┤
│ L2 Application / Orchestration                                  │
│  bot.py  agent/core.py  agent/agent.py                          │
│  agent/turn_engine.py  agent/streaming.py                       │
│  agent/input_builder.py  agent/persistence_writer.py            │
│  agent/models.py  agent/scheduler.py                            │
│  builders/*                                                     │
│  Turn/session flow, tool orchestration, persistence             │
│  Imports from: L3, L4, L5                                       │
├─────────────────────────────────────────────────────────────────┤
│ L3 Conversation Domain                                          │
│  context/manager.py  context/models.py  context/compression.py  │
│  context/checkpoint.py  context/archiver.py  context/extraction │
│  Block partitioning, token budgets, compression strategies      │
│  Imports from: L5 (TYPE_CHECKING only)                          │
├─────────────────────────────────────────────────────────────────┤
│ L4 Capability + Memory Domain                                   │
│  capability/*  memory/*  generation/*  skills/*                 │
│  Tool execution, memory retrieval, dynamic tool gen, skills     │
│  Imports from: L3 (models), L5                                  │
├─────────────────────────────────────────────────────────────────┤
│ L5 Infrastructure Adapters                                      │
│  providers/*  routing/*  config/*                               │
│  LLM inference, endpoint routing, configuration loading         │
│  Imports from: L3 (TYPE_CHECKING only for type hints)           │
└─────────────────────────────────────────────────────────────────┘

Dependency: L1 → L2 → (L3, L4) → L5
L3 ↔ L4: 独立，互不直接导入
L5 ↔ L3: 仅 TYPE_CHECKING（运行时不可反向依赖）
```

### 层边界说明

| 边界 | 允许 | 禁止 |
|------|------|------|
| L1 → L2 | Channel 调用 MindAgent.chat() | L2 导入 Channel |
| L2 → L3 | Agent 使用 ContextManager | L3 导入 Agent |
| L2 → L4 | Agent 使用 CapabilityFacade | L4 导入 Agent |
| L2 → L5 | Agent 使用 ProviderAdapter | L5 运行时导入 Agent |
| L3 ↔ L4 | 互不依赖 | 直接导入 |
| L5 → L3 | 仅 TYPE_CHECKING | 运行时导入 |

---

## 铁律约束（设计原则，不可改动）

### 1. Chat 接口只有两个

`MindAgent` 与 `Agent` 只暴露两类主 chat 入口，不允许新增其他变体：

| 入口 | 返回类型 | 说明 |
|------|----------|------|
| `chat(message, session_id, tools, on_event)` | `AgentResponse` | 主异步入口 |
| `chat_stream(message, session_id, tools)` | `AsyncIterator[str]` | 流式入口 |

```python
# OK
response = await bot.chat("hello", tools=[get_weather])
async for chunk in bot.chat_stream("hello"):
    print(chunk, end="")

# FORBIDDEN — 禁止新增同步方法或其他 chat 变体
response = bot.chat(...)
result = await bot.chat_with_agent_async(...)
```

### 2. 主链路不可绕过

所有对话路径必须经过 `Agent.chat()` → `TurnEngine.run()` → `PersistenceWriter.commit_turn()`，以保证：

- 记忆写入
- Tracer 日志
- 上下文持久化
- 工具编排

禁止在 channel 层直接调用 `_agent._run_turn()` 或裸 LLM 接口。

### 3. 全异步架构

所有公开接口必须是 `async def`，无同步版本。CLI 等顶层调用方通过 `asyncio.run()` 进入事件循环。

```python
# FORBIDDEN
def chat(self, message): ...           # 同步方法
asyncio.run(async_func())              # 嵌套事件循环
response = requests.get(...)           # 阻塞 I/O

# CPU 密集或遗留同步库必须通过 asyncio.to_thread() 卸载
result = await asyncio.to_thread(sync_func, arg)
```

### 4. Block 分区上下文管理

ContextManager 将上下文分为 7 个 Block，各有独立 token 预算，不可扁平化：

| Block | 比例 | 内容 |
|-------|------|------|
| `system_identity` | 12% | 系统提示词 |
| `skills_overview` | 8% | 技能概览 |
| `skills_detail` | 15% | 选中的技能详情 |
| `memory` | 15% | 检索到的记忆 |
| `conversation` | 35% | 对话历史（可压缩） |
| `intent_state` | 5% | 意图提示 |
| `user_input` | 10% | 用户输入 |

### 5. 工具签名失效机制

当 `tools` 参数变化时，Agent 自动重建 TurnEngine，保证 LLM 可见工具与执行器工具始终同源。

```python
# tools is not None → 完全使用传入列表
# tools is None → 回退到 tool_registry.list_tools()
```

### 6. CapabilityFacade 统一调度

所有工具执行必须经过 `CapabilityFacade.resolve_and_execute()`，不可直接调用工具函数。

### 7. 重复工具检测

TurnEngine 检测连续两次完全相同的 tool call（name + arguments），自动终止并返回 `StopReason.REPEATED_TOOL`。

---

## 核心数据流

```text
用户: "hello"
   │
   ▼
MindAgent.chat("hello", session_id="default")
   │
   ▼
Agent.chat("hello", session_id="default")
   │
   ├─ _build_turn_context(tools=None)
   │   └─ build_turn_scoped_facade(...)
   │
   ▼
Agent._run_turn(message, session_id)
   │
   ├─ InputBuilder.build("hello")
   │   ├─ _populate_skills_blocks()     → 技能匹配 + 渲染
   │   ├─ _populate_memory_block()      → 记忆检索
   │   ├─ ctx.set_user_input()          → 设置用户输入
   │   └─ 按 Block 顺序拼接 → list[Message]
   │
   ▼
TurnEngine.run(messages)
   │
   for iteration in range(max_iterations):
   │
   ├─ StreamingExecutor.execute_stream()  → LLM 调用
   │
   ├─ 无 tool_calls → COMPLETED → break
   │
   ├─ 有 tool_calls:
   │   ├─ messages.append(assistant + tool_calls)
   │   ├─ CapabilityFacade.resolve_and_execute()  → 工具执行
   │   ├─ messages.append(tool results)
   │   └─ _has_repeated_tool_call? → REPEATED_TOOL → break
   │
   └─ else: MAX_TURNS
   │
   ▼
PersistenceWriter.commit_turn()
   ├─ _commit_conversation()   → conversation block
   ├─ _commit_memory()         → short-term memory
   └─ _commit_journal()        → session journal
   │
   ▼
AgentResponse → Channel 发送
```

---

## Quick Reference

### 核心类

| 类 | 文件 | 职责 |
|----|------|------|
| `MindBot` | `bot.py` | 顶层入口，组装所有组件 |
| `MindAgent` | `agent/core.py` | 监督者，子代理管理 + Journal |
| `Agent` | `agent/agent.py` | 独立代理，LRU 会话 + 工具注册 |
| `TurnEngine` | `agent/turn_engine.py` | 对话循环 `for(iteration)` |
| `InputBuilder` | `agent/input_builder.py` | Block 拼装 → `list[Message]` |
| `ContextManager` | `context/manager.py` | 7 Block + token 预算 |
| `PersistenceWriter` | `agent/persistence_writer.py` | 三合一持久化 |
| `CapabilityFacade` | `capability/facade.py` | 工具 resolve + execute |
| `StreamingExecutor` | `agent/streaming.py` | 流式/非流式适配 |

### 核心模型

| 模型 | 关键字段 |
|------|---------|
| `Message` | `role`, `content`, `tool_calls`, `reasoning_content`, `tool_call_id`, `turn_id`, `iteration`, `message_kind`, `tool_name`, `usage`, `finish_reason`, `stop_reason`, `provider`, `is_meta`, `error` |
| `ToolCall` | `id`, `name`, `arguments` |
| `ToolResult` | `tool_call_id`, `success`, `content`, `error` |
| `ChatResponse` | `content`, `tool_calls`, `reasoning_content`, `usage`, `finish_reason` |
| `AgentResponse` | `content`, `events`, `stop_reason`, `message_trace`, `metadata` |
| `AgentEvent` | `type` (EventType), `timestamp`, `data` |

### StopReason 枚举

`COMPLETED` | `MAX_TURNS` | `LOOP_DETECTED` | `REPEATED_TOOL` | `ERROR` | `USER_ABORTED` | `APPROVAL_DENIED` | `APPROVAL_TIMEOUT` | `USER_INPUT_NEEDED`

### 压缩策略

`truncate`（默认） | `summarize` | `extract` | `mix` | `archive`

### 工具持久化策略

| 策略 | 行为 | Token 消耗 |
|------|------|-----------|
| `none` | 不保留工具中间消息 | 最低 |
| `summary` | 压缩为一条 `[Tool usage summary]` 消息 | 低 |
| `full` | 保留所有 assistant+tool_calls 和 tool results | 最高 |

### Provider 支持

OpenAI-compatible | Ollama (local) | Transformers (PyTorch)

### Channel 支持

CLI (`typer`) | HTTP (`aiohttp`) | Feishu

---

## 扩展点（可安全新增，不影响现有架构）

| 扩展点 | 方式 | 示例 |
|--------|------|------|
| 压缩策略 | 新增 `CompressionStrategy` 子类 | `SlidingWindowStrategy` |
| Provider | 新增 provider 模块 | `providers/gemini/` |
| Channel | 新增 channel 实现 | `channels/telegram.py` |
| 动态工具 | 通过 `DynamicToolManager` 生成 | 自然语言 → 工具 |
| 技能 | 新增 `SKILL.md` 文件 | `skills/my_skill/SKILL.md` |

架构改进方向（如循环模式、工具并发、流式工具、错误恢复）记录在 `docs/develop/mindbot-message-loop-analysis.md` 第 12 节，不在本文重复。

---

## Skills Reference

Read these files when you need deep knowledge:

| File | When to read |
|------|-------------|
| `docs/develop/mindbot-message-loop-analysis.md` | 理解消息循环、TurnEngine、完整数据流 |
| `docs/develop/mindbot-tool-workspace-analysis.md` | 工具系统、CapabilityFacade、动态工具生成 |
| `docs/develop/claudecode-message-loop-analysis.md` | 与 Claude Code 的架构对比 |
| `docs/architecture/layers/L1-interface-transport.md` | 新增或修改 Channel 时 |
| `docs/architecture/layers/L2-application-orchestration.md` | 改动 Agent/TurnEngine/Scheduler 时 |
| `docs/architecture/layers/L3-conversation-domain.md` | 改动 Context/压缩策略时 |
| `docs/architecture/layers/L4-capability-domain.md` | 改动工具/能力系统时 |
| `docs/architecture/layers/L5-infrastructure-adapters.md` | 新增 Provider 时 |
| `skills/design-principles.md` | 设计原则详细说明（SOLID、组合优于继承等） |
| `skills/python-conventions.md` | Python 编码规范、命名、docstring、依赖管理 |
| `skills/async-patterns.md` | 异步编程模式与 MindBot 专属约束 |
| `skills/testing-guide.md` | 测试驱动开发规范与 Checklist |

---

## Example Patterns

| Pattern | Key Files | When to reference |
|---------|-----------|-------------------|
| Tool 实现 | `capability/backends/tooling/executor.py` | 新增工具时 |
| Channel 集成 | `channels/http.py` | 新增通信渠道时 |
| 记忆检索 | `memory/manager.py`, `memory/searcher.py` | 改记忆策略时 |
| LLM Provider | `providers/openai/`, `providers/ollama/` | 接入新模型时 |
| 动态工具生成 | `generation/tool_generator.py` | 运行时创建工具时 |
| 压缩策略 | `context/compression.py` | 新增压缩算法时 |
| 技能注册 | `skills/registry.py`, `skills/selector.py` | 新增提示词技能时 |

---

*Version: v0.3.1 | Updated: 2026-04 | Maintainer: MindBot Team*
