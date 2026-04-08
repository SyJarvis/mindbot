# Claude Code 消息处理与对话循环深度分析

> 基于反编译源码 `@anthropic-ai/claude-code` v2.1.76 的分析报告
> 源码位置: `lib/claudecode/src/`

---

## 目录

- [1. 整体架构概览](#1-整体架构概览)
- [2. 消息类型体系](#2-消息类型体系)
- [3. QueryEngine — 会话管理层](#3-queryengine--会话管理层)
- [4. queryLoop — 核心对话循环](#4-queryloop--核心对话循环)
- [5. 上下文压缩策略](#5-上下文压缩策略)
- [6. 工具执行编排](#6-工具执行编排)
- [7. 错误恢复机制](#7-错误恢复机制)
- [8. 流式处理与性能优化](#8-流式处理与性能优化)
- [9. 对 MindBot 的架构启发](#9-对-mindbot-的架构启发)

---

## 1. 整体架构概览

Claude Code 的消息处理采用**三层架构**，从上到下分别是：

```
┌─────────────────────────────────────────────────────────────┐
│  QueryEngine (QueryEngine.ts, ~1295 行)                      │
│  会话管理器 — SDK/CLI 的入口                                    │
│  职责: 会话生命周期、消息持久化、token/cost 统计、权限拒绝记录        │
└────────────────────────┬────────────────────────────────────┘
                         │ submitMessage() 内部调用
┌────────────────────────▼────────────────────────────────────┐
│  query() / queryLoop() (query.ts, ~1729 行)                  │
│  核心对话循环 — while(true) 多轮迭代                            │
│  职责: 上下文压缩、LLM API 调用、工具调度、错误恢复                │
└────────────────────────┬────────────────────────────────────┘
                         │ 工具执行委托
┌────────────────────────▼────────────────────────────────────┐
│  StreamingToolExecutor / runTools() (services/tools/)        │
│  工具执行层 — 并发/串行编排                                     │
│  职责: 权限检查、Hook 执行、工具调用、结果收集                     │
└─────────────────────────────────────────────────────────────┘
```

**关键文件清单：**

| 文件 | 行数 | 职责 |
|------|------|------|
| `QueryEngine.ts` | ~1295 | 会话管理，SDK 入口 |
| `query.ts` | ~1729 | 核心对话循环 |
| `Tool.ts` | ~792 | 工具基类接口定义 |
| `tools.ts` | ~389 | 工具注册与特性门控 |
| `services/tools/toolOrchestration.ts` | ~189 | 工具批量执行编排 |
| `services/tools/StreamingToolExecutor.ts` | ~200+ | 流式工具执行器 |
| `services/tools/toolExecution.ts` | ~400+ | 单工具执行逻辑 |
| `utils/messages.ts` | ~800+ | 消息创建与转换工具函数 |

---

## 2. 消息类型体系

Claude Code 使用联合类型 (Union Type) 定义了完整的消息体系。每种消息类型在对话循环中有不同的处理逻辑：

```
Message (Union Type)
├── AssistantMessage        — LLM 响应 (含 thinking / text / tool_use blocks)
├── UserMessage             — 用户输入 / 工具结果 (tool_result)
├── SystemMessage           — 系统消息 (多种 subtype)
│   ├── compact_boundary    — 压缩边界标记
│   ├── local_command       — 斜杠命令输出
│   ├── api_error           — API 错误 (含重试信息)
│   ├── informational       — 信息性消息
│   └── ...
├── ProgressMessage         — 工具执行进度更新
├── AttachmentMessage       — 附件消息 (文件变更 / 内存 / 队列命令等)
├── StreamEvent             — API 流事件 (message_start / message_delta / message_stop)
├── TombstoneMessage        — 逻辑删除标记 (fallback 时清理孤儿消息)
├── ToolUseSummaryMessage   — 工具调用摘要 (Haiku 异步生成)
└── RequestStartEvent       — 请求开始信号
```

### 关键类型定义

`Tool.ts` 中定义了核心的工具上下文和查询链追踪：

```typescript
// src/Tool.ts — 工具使用上下文
export type ToolUseContext = {
  messages: Message[]
  options: {
    tools: Tools
    commands: Command[]
    mainLoopModel: string
    thinkingConfig: ThinkingConfig
    mcpClients: MCPServerConnection[]
    agentDefinitions: { activeAgents: AgentDefinition[]; allAgents: AgentDefinition[] }
    // ... 更多配置
  }
  getAppState: () => AppState
  setAppState: (f: (prev: AppState) => AppState) => void
  abortController: AbortController
  readFileState: FileStateCache
  queryTracking?: QueryChainTracking
  // ...
}

export type QueryChainTracking = {
  chainId: string
  depth: number
}
```

`query.ts` 中定义了循环迭代间的可变状态：

```typescript
// src/query.ts — 循环状态
type State = {
  messages: Message[]
  toolUseContext: ToolUseContext
  autoCompactTracking: AutoCompactTrackingState | undefined
  maxOutputTokensRecoveryCount: number
  hasAttemptedReactiveCompact: boolean
  maxOutputTokensOverride: number | undefined
  pendingToolUseSummary: Promise<ToolUseSummaryMessage | null> | undefined
  stopHookActive: boolean | undefined
  turnCount: number
  transition: Continue | undefined   // 上一次迭代为何继续
}
```

---

## 3. QueryEngine — 会话管理层

### 3.1 类结构

`QueryEngine` 是一个**有状态**的类，每个对话实例化一次。它封装了完整的会话生命周期：

```typescript
// src/QueryEngine.ts — QueryEngine 核心结构
export class QueryEngine {
  private config: QueryEngineConfig
  private mutableMessages: Message[]        // 可变消息历史（核心状态）
  private abortController: AbortController  // 中断控制
  private permissionDenials: SDKPermissionDenial[]
  private totalUsage: NonNullableUsage      // 累计 token 用量
  private hasHandledOrphanedPermission = false
  private readFileState: FileStateCache     // 文件读取缓存
  private discoveredSkillNames = new Set<string>()
  private loadedNestedMemoryPaths = new Set<string>()

  constructor(config: QueryEngineConfig) {
    this.config = config
    this.mutableMessages = config.initialMessages ?? []
    this.abortController = config.abortController ?? createAbortController()
    this.permissionDenials = []
    this.readFileState = config.readFileCache
    this.totalUsage = EMPTY_USAGE
  }
}
```

### 3.2 submitMessage 完整流程

`submitMessage()` 是一个**异步生成器**，yield 各种 SDK 消息给调用者：

```
submitMessage(prompt)
│
├── 1. 准备阶段
│   ├── fetchSystemPromptParts()     — 构建系统提示词（含工具描述、权限规则）
│   ├── loadMemoryPrompt()           — 加载自动记忆机制 (MEMORY.md)
│   ├── getSlashCommandToolSkills()  — 加载斜杠命令技能
│   └── loadAllPluginsCacheOnly()    — 仅缓存加载插件（不阻塞网络）
│
├── 2. 用户输入处理
│   ├── processUserInput({input, mode: 'prompt'})
│   │   ├── 解析斜杠命令
│   │   └── 返回 { messages, shouldQuery, allowedTools, model }
│   ├── mutableMessages.push(...messagesFromUserInput)
│   └── recordTranscript(messages)   — 持久化到 JSONL 转录文件
│
├── 3. 进入 query() 对话循环
│   └── for await (message of query({...}))
│       ├── 分发处理（详见下方消息分发）
│       └── 检查预算和轮次限制
│
└── 4. 结束 → yield result 消息
    └── { type: 'result', total_cost_usd, usage, num_turns, stop_reason, ... }
```

### 3.3 消息分发处理

`submitMessage()` 内部的 `for await` 循环中，对不同类型消息的处理逻辑：

```typescript
// src/QueryEngine.ts — 消息分发核心逻辑（简化）
switch (message.type) {
  case 'assistant':
    // 推入历史，yield 给 SDK 调用者
    this.mutableMessages.push(message)
    yield* normalizeMessage(message)
    break

  case 'user':
    // 工具结果消息，turnCount++
    turnCount++
    this.mutableMessages.push(message)
    yield* normalizeMessage(message)
    break

  case 'progress':
    // 进度消息，内联持久化（避免去重循环错位）
    this.mutableMessages.push(message)
    if (persistSession) {
      messages.push(message)
      void recordTranscript(messages)
    }
    yield* normalizeMessage(message)
    break

  case 'stream_event':
    // API 流事件：累计 usage，捕获 stop_reason
    if (message.event.type === 'message_start') {
      currentMessageUsage = updateUsage(currentMessageUsage, message.event.message.usage)
    }
    if (message.event.type === 'message_delta') {
      currentMessageUsage = updateUsage(currentMessageUsage, message.event.usage)
      if (message.event.delta.stop_reason != null) {
        lastStopReason = message.event.delta.stop_reason
      }
    }
    if (message.event.type === 'message_stop') {
      this.totalUsage = accumulateUsage(this.totalUsage, currentMessageUsage)
    }
    break

  case 'system':
    // compact_boundary 时截断历史，释放压缩前的消息内存
    if (message.subtype === 'compact_boundary' && message.compactMetadata) {
      // 释放压缩前的消息
      const mutableBoundaryIdx = this.mutableMessages.length - 1
      if (mutableBoundaryIdx > 0) {
        this.mutableMessages.splice(0, mutableBoundaryIdx)
      }
    }
    break

  case 'attachment':
    // 处理特殊附件：max_turns_reached、structured_output、queued_command
    if (message.attachment.type === 'max_turns_reached') {
      yield { type: 'result', subtype: 'error_max_turns', ... }
      return
    }
    break

  case 'tombstone':
    // 逻辑删除标记，跳过
    break
}
```

### 3.4 ask() 便捷函数

`ask()` 是一个无状态的便捷包装，内部创建 `QueryEngine` 实例：

```typescript
// src/QueryEngine.ts — 便捷函数
export async function* ask({
  commands, prompt, cwd, tools, mcpClients,
  canUseTool, mutableMessages, /* ... */
}: AskParams): AsyncGenerator<SDKMessage, void, unknown> {
  const engine = new QueryEngine({
    cwd, tools, commands, mcpClients,
    initialMessages: mutableMessages,
    // ... 所有配置透传
  })

  try {
    yield* engine.submitMessage(prompt, { uuid: promptUuid, isMeta })
  } finally {
    setReadFileCache(engine.getReadFileState())
  }
}
```

---

## 4. queryLoop — 核心对话循环

### 4.1 总体结构

`queryLoop()` 是整个系统的核心，位于 `query.ts:241-1729`。它使用 **`while(true)` 无限循环 + `state = nextState + continue`** 的模式，每次迭代是一个完整的"压缩→API→工具→判断"周期：

```
queryLoop(params)
│
├── 初始化 state = { messages, toolUseContext, turnCount: 1, ... }
├── 初始化 budgetTracker, taskBudgetRemaining
├── using pendingMemoryPrefetch = startRelevantMemoryPrefetch(...)
│
└── while (true) {
    │
    ├── [步骤 1] 上下文预处理与压缩
    │   ├── getMessagesAfterCompactBoundary(messages)
    │   ├── applyToolResultBudget()           — 工具结果大小限制
    │   ├── snipCompactIfNeeded()             — 历史裁剪 (feature gate)
    │   ├── microcompact()                    — 微压缩
    │   ├── applyCollapsesIfNeeded()          — 上下文折叠 (实验性)
    │   └── autocompact()                     — 自动压缩
    │
    ├── [步骤 2] Token 溢出检查
    │   └── isAtBlockingLimit → return { reason: 'blocking_limit' }
    │
    ├── [步骤 3] 调用 LLM API (streaming)
    │   └── for await (message of callModel({...}))
    │       ├── 收集 assistantMessages
    │       ├── 收集 toolUseBlocks → 设置 needsFollowUp = true
    │       ├── StreamingToolExecutor 并行执行已到达的工具
    │       └── yield 消息给上层
    │
    ├── [步骤 4] 后处理判断
    │   ├── [中断] abort signal → yield 中断消息, return
    │   ├── [无需工具] !needsFollowUp
    │   │   ├── 错误恢复（详见第 7 节）
    │   │   ├── handleStopHooks()
    │   │   └── return { reason: 'completed' }
    │   └── [需要工具] needsFollowUp → 继续
    │
    ├── [步骤 5] 工具执行
    │   ├── StreamingToolExecutor.getRemainingResults() 或 runTools()
    │   ├── 收集 toolResults
    │   ├── getAttachmentMessages()  — 附件（文件变更、内存预取、队列命令）
    │   ├── pendingMemoryPrefetch    — 记忆预取
    │   └── skillPrefetch            — 技能预取
    │
    ├── [步骤 6] 更新状态，继续循环
    │   ├── nextTurnCount = turnCount + 1
    │   ├── maxTurns 检查
    │   └── state = { messages: [...query, ...assistant, ...results], turnCount: nextTurnCount }
    │   → continue → 回到 while(true) 开头
  }
```

### 4.2 循环入口与状态初始化

```typescript
// src/query.ts — 循环入口
async function* queryLoop(
  params: QueryParams,
  consumedCommandUuids: string[],
): AsyncGenerator<StreamEvent | RequestStartEvent | Message | TombstoneMessage | ToolUseSummaryMessage, Terminal> {

  // 不可变参数 — 循环中不会被重新赋值
  const { systemPrompt, userContext, systemContext, canUseTool, fallbackModel,
          querySource, maxTurns, skipCacheWrite } = params
  const deps = params.deps ?? productionDeps()

  // 可变跨迭代状态 — 每次 continue 时整体替换
  let state: State = {
    messages: params.messages,
    toolUseContext: params.toolUseContext,
    maxOutputTokensOverride: params.maxOutputTokensOverride,
    autoCompactTracking: undefined,
    stopHookActive: undefined,
    maxOutputTokensRecoveryCount: 0,
    hasAttemptedReactiveCompact: false,
    turnCount: 1,
    pendingToolUseSummary: undefined,
    transition: undefined,
  }

  // ...
}
```

### 4.3 API 调用与流式消费

```typescript
// src/query.ts — API 调用核心循环（简化）
let attemptWithFallback = true

try {
  while (attemptWithFallback) {
    attemptWithFallback = false
    try {
      let streamingFallbackOccured = false

      // 流式调用 LLM API
      for await (const message of deps.callModel({
        messages: prependUserContext(messagesForQuery, userContext),
        systemPrompt: fullSystemPrompt,
        thinkingConfig: toolUseContext.options.thinkingConfig,
        tools: toolUseContext.options.tools,
        signal: toolUseContext.abortController.signal,
        options: {
          model: currentModel,
          // ... 大量配置
        },
      })) {
        // 流式 fallback 发生时，清理孤儿消息
        if (streamingFallbackOccured) {
          for (const msg of assistantMessages) {
            yield { type: 'tombstone', message: msg }
          }
          assistantMessages.length = 0
          toolResults.length = 0
          toolUseBlocks.length = 0
        }

        // yield 消息给上层（可被 withhold 机制拦截）
        if (!withheld) {
          yield yieldMessage
        }

        // 收集 assistant 消息和 tool_use 块
        if (message.type === 'assistant') {
          assistantMessages.push(message)
          const msgToolUseBlocks = message.message.content.filter(
            content => content.type === 'tool_use'
          ) as ToolUseBlock[]
          if (msgToolUseBlocks.length > 0) {
            toolUseBlocks.push(...msgToolUseBlocks)
            needsFollowUp = true
          }

          // 流式工具执行：工具块到达时立即开始执行
          if (streamingToolExecutor && !toolUseContext.abortController.signal.aborted) {
            for (const toolBlock of msgToolUseBlocks) {
              streamingToolExecutor.addTool(toolBlock, message)
            }
          }
        }

        // 流式执行中已完成的工具结果
        if (streamingToolExecutor && !toolUseContext.abortController.signal.aborted) {
          for (const result of streamingToolExecutor.getCompletedResults()) {
            if (result.message) {
              yield result.message
              toolResults.push(...normalizeMessagesForAPI([result.message], tools))
            }
          }
        }
      }
    } catch (innerError) {
      // Fallback 模型切换
      if (innerError instanceof FallbackTriggeredError && fallbackModel) {
        currentModel = fallbackModel
        attemptWithFallback = true
        // 清空并重试...
        continue
      }
      throw innerError
    }
  }
} catch (error) {
  // 顶层错误处理
  yield* yieldMissingToolResultBlocks(assistantMessages, errorMessage)
  yield createAssistantAPIErrorMessage({ content: errorMessage })
  return { reason: 'model_error', error }
}
```

### 4.4 工具执行后的状态传递

```typescript
// src/query.ts — 工具执行后的状态更新与 continue
const nextTurnCount = turnCount + 1

// maxTurns 检查
if (maxTurns && nextTurnCount > maxTurns) {
  yield createAttachmentMessage({ type: 'max_turns_reached', maxTurns, turnCount: nextTurnCount })
  return { reason: 'max_turns', turnCount: nextTurnCount }
}

// 组装下一次迭代的状态
const next: State = {
  messages: [...messagesForQuery, ...assistantMessages, ...toolResults],
  toolUseContext: toolUseContextWithQueryTracking,
  autoCompactTracking: tracking,
  turnCount: nextTurnCount,
  maxOutputTokensRecoveryCount: 0,
  hasAttemptedReactiveCompact: false,
  pendingToolUseSummary: nextPendingToolUseSummary,
  maxOutputTokensOverride: undefined,
  stopHookActive,
  transition: { reason: 'next_turn' },
}
state = next
// → continue → 回到 while(true) 开头，开始下一轮压缩 + API 调用
```

---

## 5. 上下文压缩策略

Claude Code 有一个**多层次的上下文压缩管道**，在每次 API 调用前依次执行：

```
原始消息
  │
  ├── 1. getMessagesAfterCompactBoundary()  — 截取最近压缩边界之后的消息
  │
  ├── 2. applyToolResultBudget()            — 限制工具结果的总体大小
  │                                         （超大结果会被内容替换/截断）
  │
  ├── 3. snipCompactIfNeeded() [HISTORY_SNIP]
  │     └── 基于规则的历史裁剪（移除早期详细内容，保留摘要）
  │
  ├── 4. microcompact()                     — 微压缩
  │     └── 使用缓存编辑或轻量级摘要，减少 token 占用
  │
  ├── 5. applyCollapsesIfNeeded() [CONTEXT_COLLAPSE]
  │     └── 实验性：将详细消息折叠为摘要视图
  │
  └── 6. autocompact()                      — 自动压缩（主力策略）
        └── 当 token 接近上下文窗口上限时触发
            调用 LLM 生成对话摘要，替换历史消息
            产出 compact_boundary 消息标记边界
```

### 自动压缩触发与执行

```typescript
// src/query.ts — autocompact 调用
const { compactionResult, consecutiveFailures } = await deps.autocompact(
  messagesForQuery,
  toolUseContext,
  {
    systemPrompt,
    userContext,
    systemContext,
    toolUseContext,
    forkContextMessages: messagesForQuery,
  },
  querySource,
  tracking,
  snipTokensFreed,   // snip 释放的 token 数，影响阈值计算
)

if (compactionResult) {
  const { preCompactTokenCount, postCompactTokenCount, compactionUsage } = compactionResult

  // 记录分析事件
  logEvent('tengu_auto_compact_succeeded', {
    originalMessageCount: messages.length,
    preCompactTokenCount,
    postCompactTokenCount,
    // ...
  })

  // 重置追踪状态
  tracking = {
    compacted: true,
    turnId: deps.uuid(),
    turnCounter: 0,
    consecutiveFailures: 0,
  }

  // 构建压缩后的消息并替换
  const postCompactMessages = buildPostCompactMessages(compactionResult)
  for (const message of postCompactMessages) {
    yield message   // yield compact_boundary 等消息
  }
  messagesForQuery = postCompactMessages
}
```

### 压缩边界后的内存释放

在 `QueryEngine.submitMessage()` 中，收到 `compact_boundary` 消息后，会截断 `mutableMessages` 释放压缩前的消息内存：

```typescript
// src/QueryEngine.ts — 压缩边界后的内存释放
if (message.subtype === 'compact_boundary' && message.compactMetadata) {
  // 释放压缩前的消息（boundary 是最后一个元素）
  const mutableBoundaryIdx = this.mutableMessages.length - 1
  if (mutableBoundaryIdx > 0) {
    this.mutableMessages.splice(0, mutableBoundaryIdx)
  }
  const localBoundaryIdx = messages.length - 1
  if (localBoundaryIdx > 0) {
    messages.splice(0, localBoundaryIdx)
  }

  yield {
    type: 'system',
    subtype: 'compact_boundary',
    session_id: getSessionId(),
    uuid: message.uuid,
    compact_metadata: toSDKCompactMetadata(message.compactMetadata),
  }
}
```

---

## 6. 工具执行编排

### 6.1 两种执行模式

Claude Code 支持两种工具执行模式：

**传统模式 — `runTools()`**：
```
所有 tool_use 块到达后才开始执行
  │
  ├── partitionToolCalls() → 按并发安全性分区
  │     ├── [只读工具] → runToolsConcurrently() (最多 10 并发)
  │     └── [写操作工具] → runToolsSerially() (串行执行)
  │
  └── 逐批执行，yield 结果
```

**流式模式 — `StreamingToolExecutor`**：
```
模型流式输出期间就开始执行工具
  │
  ├── addTool(block, message)  — 工具块到达时立即入队并启动执行
  ├── getCompletedResults()    — 在流循环中 yield 已完成的结果
  ├── getRemainingResults()    — 流结束后获取剩余结果
  └── discard()                — fallback 时丢弃所有结果
```

### 6.2 工具分区策略

```typescript
// src/services/tools/toolOrchestration.ts — 工具分区
function partitionToolCalls(
  toolUseMessages: ToolUseBlock[],
  toolUseContext: ToolUseContext,
): Batch[] {
  return toolUseMessages.reduce((acc: Batch[], toolUse) => {
    const tool = findToolByName(toolUseContext.options.tools, toolUse.name)
    const parsedInput = tool?.inputSchema.safeParse(toolUse.input)
    const isConcurrencySafe = parsedInput?.success
      ? (() => {
          try {
            return Boolean(tool?.isConcurrencySafe(parsedInput.data))
          } catch {
            return false  // 解析失败时保守处理
          }
        })()
      : false

    // 连续的并发安全工具合并为一批
    if (isConcurrencySafe && acc[acc.length - 1]?.isConcurrencySafe) {
      acc[acc.length - 1]!.blocks.push(toolUse)
    } else {
      acc.push({ isConcurrencySafe, blocks: [toolUse] })
    }
    return acc
  }, [])
}
```

### 6.3 StreamingToolExecutor

```typescript
// src/services/tools/StreamingToolExecutor.ts — 流式工具执行器
export class StreamingToolExecutor {
  private tools: TrackedTool[] = []
  private toolUseContext: ToolUseContext
  private siblingAbortController: AbortController  // Bash 出错时杀死兄弟进程
  private discarded = false

  type TrackedTool = {
    id: string
    block: ToolUseBlock
    assistantMessage: AssistantMessage
    status: 'queued' | 'executing' | 'completed' | 'yielded'
    isConcurrencySafe: boolean
    promise?: Promise<void>
    results?: Message[]
    pendingProgress: Message[]   // 进度消息立即 yield
    contextModifiers?: Array<(context: ToolUseContext) => ToolUseContext>
  }

  // 工具块到达时立即入队执行
  addTool(block: ToolUseBlock, assistantMessage: AssistantMessage): void {
    // ... 权限检查、并发控制、启动执行
  }

  // 在流循环中获取已完成的结果
  getCompletedResults(): MessageUpdate[] { /* ... */ }

  // 流结束后获取所有剩余结果
  async *getRemainingResults(): AsyncGenerator<MessageUpdate> { /* ... */ }

  // fallback 时丢弃所有结果
  discard(): void {
    this.discarded = true
  }
}
```

### 6.4 单工具执行流程

```
runToolUse(toolBlock, assistantMessage, canUseTool, toolUseContext)
│
├── 1. runPreToolUseHooks()          — Hook 前处理
│
├── 2. canUseTool()                  — 权限检查
│   ├── deny → yield 权限拒绝消息，return
│   └── allow → 继续
│
├── 3. tool.execute(input, toolUseContext) — 执行工具
│   └── 流式 yield ProgressMessage（进度更新）
│
├── 4. processToolResultBlock()      — 处理结果
│   ├── 大小限制（超大结果截断/替换）
│   └── 内容持久化
│
├── 5. runPostToolUseHooks()         — Hook 后处理
│   ├── 成功 Hook
│   └── 失败 Hook (on error)
│
└── 6. yield tool_result 消息
```

---

## 7. 错误恢复机制

Claude Code 有非常精细的多层错误恢复策略。核心设计是 **withhold-and-recover（隐藏-恢复）模式**：先隐藏错误消息，尝试恢复，失败后再展示。

### 7.1 Prompt-too-long (413) 恢复

```
API 返回 413 (prompt too long)
  │
  ├── 消息被 withhold（不 yield 给上层）
  │
  ├── 尝试路径 1: Context Collapse Drain
  │   ├── 提交已暂存的上下文折叠
  │   ├── drained.committed > 0?
  │   │   ├── YES → state = { messages: drained.messages, transition: 'collapse_drain_retry' }
  │   │   │         → continue（重试 API 调用）
  │   │   └── NO  → 走路径 2
  │   └── 防止死循环：检查 transition !== 'collapse_drain_retry'
  │
  ├── 尝试路径 2: Reactive Compact（全量压缩）
  │   ├── 调用 LLM 生成对话摘要
  │   ├── compacted?
  │   │   ├── YES → yield postCompactMessages
  │   │   │         state = { transition: 'reactive_compact_retry' }
  │   │   │         → continue（重试 API 调用）
  │   │   └── NO  → 走路径 3
  │   └── 防止死循环：hasAttemptedReactiveCompact 标志
  │
  └── 路径 3: 恢复失败
      ├── yield 被隐藏的错误消息
      └── return { reason: 'prompt_too_long' }
```

```typescript
// src/query.ts — prompt-too-long 恢复（简化）
const isWithheld413 = lastMessage?.type === 'assistant'
  && lastMessage.isApiErrorMessage
  && isPromptTooLongMessage(lastMessage)

if (isWithheld413) {
  // 路径 1: collapse drain
  if (feature('CONTEXT_COLLAPSE') && contextCollapse
      && state.transition?.reason !== 'collapse_drain_retry') {
    const drained = contextCollapse.recoverFromOverflow(messagesForQuery, querySource)
    if (drained.committed > 0) {
      state = { messages: drained.messages, transition: { reason: 'collapse_drain_retry', committed: drained.committed } }
      continue
    }
  }
}
if ((isWithheld413 || isWithheldMedia) && reactiveCompact) {
  const compacted = await reactiveCompact.tryReactiveCompact({ ... })
  if (compacted) {
    const postCompactMessages = buildPostCompactMessages(compacted)
    for (const msg of postCompactMessages) yield msg
    state = { messages: postCompactMessages, hasAttemptedReactiveCompact: true, transition: { reason: 'reactive_compact_retry' } }
    continue
  }
  // 恢复失败
  yield lastMessage
  return { reason: 'prompt_too_long' }
}
```

### 7.2 Max-output-tokens 恢复

```
API 返回 max_output_tokens（输出 token 耗尽，模型被截断）
  │
  ├── 消息被 withhold
  │
  ├── 尝试 1: 升级 output tokens 上限
  │   ├── 从默认 8k → 64k
  │   ├── state = { maxOutputTokensOverride: 65536, transition: 'max_output_tokens_escalate' }
  │   └── continue（静默重试，不注入额外消息）
  │
  ├── 尝试 2: 多轮恢复（最多 3 次）
  │   ├── 注入 meta 消息："Output token limit hit. Resume directly..."
  │   ├── state = { messages: [...query, ...assistant, recoveryMessage], maxOutputTokensRecoveryCount + 1 }
  │   └── continue（模型从截断处继续）
  │
  └── 恢复耗尽 → yield 被隐藏的错误消息
```

```typescript
// src/query.ts — max-output-tokens 恢复
if (isWithheldMaxOutputTokens(lastMessage)) {
  // 尝试 1: 升级到 64k
  const capEnabled = getFeatureValue_CACHED_MAY_BE_STALE('tengu_otk_slot_v1', false)
  if (capEnabled && maxOutputTokensOverride === undefined) {
    const next: State = {
      messages: messagesForQuery,
      maxOutputTokensOverride: ESCALATED_MAX_TOKENS,  // 65536
      transition: { reason: 'max_output_tokens_escalate' },
      // ...
    }
    state = next
    continue
  }

  // 尝试 2: 多轮恢复
  if (maxOutputTokensRecoveryCount < MAX_OUTPUT_TOKENS_RECOVERY_LIMIT) {
    const recoveryMessage = createUserMessage({
      content: `Output token limit hit. Resume directly — no apology, no recap of what you were doing. ` +
               `Pick up mid-thought if that is where the cut happened. Break remaining work into smaller pieces.`,
      isMeta: true,
    })
    const next: State = {
      messages: [...messagesForQuery, ...assistantMessages, recoveryMessage],
      maxOutputTokensRecoveryCount: maxOutputTokensRecoveryCount + 1,
      transition: { reason: 'max_output_tokens_recovery', attempt: maxOutputTokensRecoveryCount + 1 },
      // ...
    }
    state = next
    continue
  }

  // 恢复耗尽
  yield lastMessage
}
```

### 7.3 Model Fallback

当主模型不可用时，切换到备选模型：

```typescript
// src/query.ts — Model Fallback
try {
  // ... API 调用 ...
} catch (innerError) {
  if (innerError instanceof FallbackTriggeredError && fallbackModel) {
    currentModel = fallbackModel
    attemptWithFallback = true

    // 为孤儿 assistant 消息生成 tool_result 错误
    yield* yieldMissingToolResultBlocks(assistantMessages, 'Model fallback triggered')
    assistantMessages.length = 0
    toolResults.length = 0
    toolUseBlocks.length = 0

    // 丢弃流式执行器中的待处理结果
    if (streamingToolExecutor) {
      streamingToolExecutor.discard()
      streamingToolExecutor = new StreamingToolExecutor(tools, canUseTool, toolUseContext)
    }

    // 跨模型 thinking 签名不兼容，需要剥离
    if (process.env.USER_TYPE === 'ant') {
      messagesForQuery = stripSignatureBlocks(messagesForQuery)
    }

    yield createSystemMessage(
      `Switched to ${renderModelName(fallbackModel)} due to high demand for ${renderModelName(originalModel)}`,
      'warning',
    )
    continue
  }
  throw innerError
}
```

### 7.4 所有 continue 转换路径汇总

| transition.reason | 触发条件 | 说明 |
|---|---|---|
| `next_turn` | 工具执行完成，正常下一轮 | 最常见的路径 |
| `collapse_drain_retry` | 413 + context collapse drain | 折叠已暂存的上下文 |
| `reactive_compact_retry` | 413 / 媒体错误 + reactive compact | 全量压缩后重试 |
| `max_output_tokens_escalate` | output token 耗尽 + 首次 | 从 8k 升级到 64k |
| `max_output_tokens_recovery` | output token 耗尽 + 升级后仍不够 | 注入恢复消息 |
| `stop_hook_blocking` | stop hook 阻止继续 | 注入 blocking 错误 |
| `token_budget_continuation` | token 预算未用完 | 注入 nudge 消息继续 |

---

## 8. 流式处理与性能优化

### 8.1 流式工具执行

核心优化：**不等模型输出全部完成，工具块到达时就开始执行**。

```
模型流式输出:  [text] [tool_use_1] [text] [tool_use_2] [text]
                     ↓                    ↓
执行器:        立即启动 tool_1       立即启动 tool_2
                     ↓                    ↓
结果:          [result_1 ready] ←─────────┘ [result_2 ready]
```

### 8.2 工具调用摘要异步生成

工具执行完成后，使用 Haiku 模型**异步**生成摘要，不阻塞下一轮 API 调用：

```typescript
// src/query.ts — 异步工具摘要
let nextPendingToolUseSummary: Promise<ToolUseSummaryMessage | null> | undefined

if (config.gates.emitToolUseSummaries && toolUseBlocks.length > 0) {
  // 不 await，在下一轮迭代中 consume
  nextPendingToolUseSummary = generateToolUseSummary({
    tools: toolInfoForSummary,
    signal: toolUseContext.abortController.signal,
    isNonInteractiveSession: toolUseContext.options.isNonInteractiveSession,
    lastAssistantText,
  })
    .then(summary => summary ? createToolUseSummaryMessage(summary, toolUseIds) : null)
    .catch(() => null)
}

// 在下一轮迭代开始时 consume
if (pendingToolUseSummary) {
  const summary = await pendingToolUseSummary
  if (summary) yield summary
}
```

### 8.3 记忆预取

对话开始时异步预取相关记忆文件，不阻塞首条 API 调用：

```typescript
// src/query.ts — 记忆预取
using pendingMemoryPrefetch = startRelevantMemoryPrefetch(
  state.messages,
  state.toolUseContext,
)

// 在工具执行完成后 consume
if (pendingMemoryPrefetch && pendingMemoryPrefetch.settledAt !== null
    && pendingMemoryPrefetch.consumedOnIteration === -1) {
  const memoryAttachments = filterDuplicateMemoryAttachments(
    await pendingMemoryPrefetch.promise,
    toolUseContext.readFileState,
  )
  for (const memAttachment of memoryAttachments) {
    const msg = createAttachmentMessage(memAttachment)
    yield msg
    toolResults.push(msg)
  }
  pendingMemoryPrefetch.consumedOnIteration = turnCount - 1
}
```

### 8.4 消息持久化策略

不同类型消息有不同的持久化策略：

```typescript
// src/QueryEngine.ts — 持久化策略
if (message.type === 'assistant') {
  // assistant 消息：fire-and-forget（利用写入队列的 100ms 延迟合并）
  void recordTranscript(messages)
} else if (message.type === 'progress') {
  // 进度消息：内联持久化（避免去重循环错位）
  messages.push(message)
  void recordTranscript(messages)
} else {
  // user / compact_boundary 等关键消息：await 持久化
  await recordTranscript(messages)
}
```

---

## 9. 对 MindBot 的架构启发

### 9.1 对话循环模式

Claude Code 的 `while(true) + state = nextState + continue` 模式比递归更优：
- 避免递归栈溢出（长对话可能有数百轮）
- 状态替换是原子的，不会出现半更新状态
- `transition` 字段让每次"为什么继续"有迹可循

**MindBot 可借鉴**：将当前的递归对话循环重构为 while(true) + 状态传递模式。

### 9.2 多层压缩管道

四层压缩（snip → microcompact → context collapse → autocompact）按成本从低到高排列：
- 先尝试廉价操作（裁剪、缓存编辑）
- 最后才调用 LLM 生成摘要（成本最高但效果最好）

### 9.3 Withhold-and-Recover 模式

错误恢复的"隐藏-恢复"模式值得学习：
- 不要在错误发生时立即展示给用户
- 先尝试自动恢复（压缩、升级限制等）
- 只有所有恢复路径失败后才展示错误

### 9.4 流式工具执行

StreamingToolExecutor 是关键的性能优化，可以让工具执行和模型流式输出**并行**进行。对于 MindBot 的 provider 架构，可以在流式输出解析 tool_use 块时立即启动执行。

### 9.5 工具并发控制

`isConcurrencySafe()` 分区策略简单实用：
- 只读工具（Glob, Grep, FileRead）可并行
- 写操作工具（FileEdit, FileWrite, Bash）必须串行
- 按连续性分区（连续的只读工具合并为一批并行执行）

---

*文档生成时间: 2026-04-08*
*分析源码版本: claude-code v2.1.76*
