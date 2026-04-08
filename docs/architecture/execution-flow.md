---
title: 执行流程
---

# 执行流程

本文档描述 MindBot 从用户输入到最终响应的完整执行路径，以及 TurnEngine 内部的迭代循环机制。

## 完整请求流程

以下时序图展示了从用户发送消息到获得响应的完整数据流：

```mermaid
sequenceDiagram
    actor User as 用户
    participant Bot as MindBot<br/>(bot.py)
    participant Mind as MindAgent<br/>(agent/core.py)
    participant Agent as Agent<br/>(agent/agent.py)
    participant IB as InputBuilder<br/>(input_builder.py)
    participant CM as ContextManager<br/>(context/manager.py)
    participant TE as TurnEngine<br/>(turn_engine.py)
    participant SE as StreamingExecutor<br/>(streaming.py)
    participant PA as ProviderAdapter<br/>(providers/adapter.py)
    participant LLM as LLM Provider
    participant CF as CapabilityFacade<br/>(capability/facade.py)
    participant PW as PersistenceWriter<br/>(persistence_writer.py)
    participant MM as MemoryManager<br/>(memory/manager.py)
    participant SJ as SessionJournal<br/>(session/store.py)

    User->>Bot: chat(message, session_id)
    activate Bot
    Bot->>Mind: chat(message, session_id, on_event, tools)
    activate Mind
    Mind->>Agent: chat(message, session_id, on_event, tools)
    activate Agent

    Note over Agent: _build_turn_context()<br/>构建工具/能力视图

    Agent->>Agent: _build_turn_context(tools)
    Note over Agent: 生成 _TurnExecutionContext<br/>tools + CapabilityFacade

    rect rgb(240, 248, 255)
        Note over Agent,IB: 阶段 1：组装 LLM 输入
        Agent->>IB: build(message, session_id)
        activate IB
        IB->>IB: _populate_skills_blocks(query)
        IB->>IB: _populate_memory_block(query)
        IB->>MM: search(query, top_k)
        MM-->>IB: MemoryChunk[]
        IB->>CM: set_user_input(user_msg)
        IB->>CM: get_block_messages() x 7
        CM-->>IB: 组装后的 Message[]
        IB-->>Agent: messages: list[Message]
        deactivate IB
    end

    rect rgb(255, 248, 240)
        Note over Agent,TE: 阶段 2：TurnEngine 执行循环
        Agent->>TE: run(messages, on_event, turn_id)
        activate TE

        loop iteration = 0 .. max_iterations - 1
            TE->>SE: execute_stream(messages, on_event, tools)
            activate SE
            SE->>PA: chat(messages, tools=tools) 或 chat_stream(messages)
            activate PA
            PA->>LLM: API 调用
            LLM-->>PA: ChatResponse
            PA-->>SE: ChatResponse
            deactivate PA
            SE-->>TE: ChatResponse (content + tool_calls)
            deactivate SE

            alt 无 tool_calls（最终回复）
                TE->>TE: 记录 content, stop_reason=COMPLETED
                Note over TE: 跳出循环
            else 有 tool_calls
                TE->>TE: 追加 assistant tool_call 消息到 messages

                loop 每个 tool_call
                    TE->>CF: resolve_and_execute(query, arguments)
                    activate CF
                    CF-->>TE: 工具执行结果 (str)
                    deactivate CF
                    TE->>TE: 追加 tool_result 消息到 messages
                end

                TE->>TE: _has_repeated_tool_call() 检测
                alt 检测到重复
                    Note over TE: stop_reason=REPEATED_TOOL<br/>跳出循环
                end
            end
        end

        TE-->>Agent: AgentResponse (content, message_trace, stop_reason)
        deactivate TE
    end

    rect rgb(240, 255, 240)
        Note over Agent,PW: 阶段 3：持久化提交
        Agent->>PW: commit_turn(message, response, session_id)
        activate PW
        PW->>CM: add_conversation_message("user", text)
        PW->>CM: add_conversation_message("assistant", text)
        PW->>CM: clear_user_input() / clear_intent_state()
        PW->>MM: append_to_short_term(user + assistant)
        PW->>SJ: append(session_id, entries)
        PW-->>Agent: 提交完成
        deactivate PW
    end

    Agent-->>Mind: AgentResponse
    deactivate Agent
    Mind-->>Bot: AgentResponse
    deactivate Mind
    Bot-->>User: AgentResponse
    deactivate Bot
```

## TurnEngine 迭代循环

TurnEngine 是整个执行流程的核心，负责驱动 "LLM 调用 - 工具执行" 的迭代循环。以下流程图展示了单次迭代的完整决策过程：

```mermaid
flowchart TD
    START([开始 TurnEngine.run]) --> INIT["初始化 AgentResponse<br/>生成 turn_id<br/>记录 initial_len = len(messages)"]

    INIT --> LOOP{"iteration < max_iterations?"}

    LOOP -->|"否"| MAX_TURNS["stop_reason = MAX_TURNS"]
    LOOP -->|"是"| LLM_CALL["StreamingExecutor.execute_stream()<br/>调用 LLM"]

    LLM_CALL --> CHECK_TC{"响应中包含<br/>tool_calls?"}

    CHECK_TC -->|"否 - 纯文本回复"| RECORD["记录 response.content<br/>记录 metadata<br/>stop_reason = COMPLETED"]
    RECORD --> BUILD_TRACE["构建 message_trace<br/>messages[initial_len:]"]

    CHECK_TC -->|"是 - 需要工具调用"| APPEND_ASSISTANT["追加 assistant tool_call 消息<br/>到 messages"]
    APPEND_ASSISTANT --> EXEC_TOOLS["执行工具调用"]

    subgraph EXEC_TOOLS_LOOP["工具执行循环"]
        direction TB
        NEXT_TC["取出下一个 tool_call"] --> EMIT_EXEC["emit AgentEvent.tool_executing"]
        EMIT_EXEC --> CF_EXEC["CapabilityFacade.resolve_and_execute()"]
        CF_EXEC --> CHECK_SUCCESS{"执行成功?"}
        CHECK_SUCCESS -->|"成功"| APPEND_RESULT["追加 tool_result 消息<br/>到 messages"]
        CHECK_SUCCESS -->|"失败"| APPEND_ERROR["追加 error tool_result<br/>到 messages"]
        APPEND_RESULT --> MORE_TC{"还有更多<br/>tool_call?"}
        APPEND_ERROR --> MORE_TC
        MORE_TC -->|"是"| NEXT_TC
        MORE_TC -->|"否"| DONE_EXEC["工具执行完毕"]
    end

    DONE_EXEC --> CHECK_REPEAT{"_has_repeated_<br/>tool_call()?"}
    CHECK_REPEAT -->|"是 - 连续相同调用"| STOP_REPEAT["stop_reason = REPEATED_TOOL"]
    CHECK_REPEAT -->|"否 - 正常继续"| LOOP

    STOP_REPEAT --> BUILD_TRACE
    MAX_TURNS --> BUILD_TRACE
    BUILD_TRACE --> FINAL_CHECK{"stop_reason == COMPLETED<br/>且 trace 末尾无<br/>assistant 文本消息?"}
    FINAL_CHECK -->|"是"| APPEND_FINAL["追加最终 assistant 消息<br/>到 trace"]
    FINAL_CHECK -->|"否"| SET_STOP["设置 trace 最后一条消息的<br/>stop_reason"]
    APPEND_FINAL --> SET_STOP
    SET_STOP --> RETURN(["返回 AgentResponse"])

    style START fill:#4caf50,color:#fff
    style RETURN fill:#4caf50,color:#fff
    style MAX_TURNS fill:#ff9800,color:#fff
    style STOP_REPEAT fill:#f44336,color:#fff
    style RECORD fill:#2196f3,color:#fff
    style LLM_CALL fill:#9c27b0,color:#fff
    style CF_EXEC fill:#ff5722,color:#fff
```

## 关键数据模型

以下是执行流程中各步骤涉及的核心数据模型及其流转关系。

### 消息模型（贯穿全流程）

| 模型 | 模块 | 关键字段 | 说明 |
|------|------|---------|------|
| `Message` | `context/models.py` | `role`, `content`, `tool_calls`, `tool_call_id`, `turn_id`, `iteration`, `message_kind`, `provider`, `usage`, `timestamp`, `token_count` | 统一多模态消息格式，贯穿 InputBuilder、TurnEngine、PersistenceWriter |
| `MessageContent` | `context/models.py` | `str` 或 `list[TextPart \| ImagePart]` | 消息内容：纯文本或多模态部件列表 |
| `ToolCall` | `context/models.py` | `id`, `name`, `arguments` | LLM 发起的工具调用请求 |
| `ToolResult` | `context/models.py` | `tool_call_id`, `success`, `content`, `error` | 工具执行结果 |

### 响应模型（L2 编排层）

| 模型 | 模块 | 关键字段 | 说明 |
|------|------|---------|------|
| `AgentResponse` | `agent/models.py` | `content`, `events`, `stop_reason`, `message_trace`, `metadata` | Agent 执行结果，包含消息追踪（权威记录） |
| `AgentEvent` | `agent/models.py` | `type` (EventType), `timestamp`, `data` | 流式事件：thinking / delta / tool_executing / tool_result / complete / error |
| `StopReason` | `agent/models.py` | `COMPLETED`, `MAX_TURNS`, `REPEATED_TOOL`, `ERROR`, `USER_ABORTED`, `APPROVAL_DENIED`, `USER_INPUT_NEEDED` | 循环终止原因枚举 |
| `ChatResponse` | `context/models.py` | `content`, `tool_calls`, `reasoning_content`, `provider`, `finish_reason`, `usage` | LLM Provider 统一响应格式 |

### 能力模型（L4 能力层）

| 模型 | 模块 | 关键字段 | 说明 |
|------|------|---------|------|
| `Capability` | `capability/models.py` | `id`, `name`, `description`, `parameters_schema`, `capability_type`, `backend_id` | 统一能力描述，编排层唯一依赖的能力抽象 |
| `CapabilityQuery` | `capability/models.py` | `capability_id`, `name`, `description_hint`, `capability_type` | 能力查找参数 |

### 上下文块模型（L3 领域层）

| 模型 | 模块 | 关键字段 | 说明 |
|------|------|---------|------|
| `ContextBlock` | `context/manager.py` | `name`, `max_tokens`, `messages` | 单个上下文块，持有消息列表和 token 预算 |
| `ContextManager` | `context/manager.py` | `_blocks` (7 个 ContextBlock), `max_tokens` | 7 块上下文窗口管理器 |

## 数据流转路径

```mermaid
flowchart LR
    subgraph 输入阶段
        U["用户消息<br/>(str)"]
        SP["系统提示词<br/>(str)"]
        MEM["记忆检索<br/>(MemoryChunk[])"]
        SK["技能指令<br/>(SkillDefinition)"]
    end

    subgraph 组装阶段
        IB["InputBuilder.build()"]
    end

    subgraph 执行阶段
        MSGS["messages: list[Message]"]
        TE["TurnEngine 循环"]
        TC["ToolCall[]"]
        TR["ToolResult[]"]
    end

    subgraph 输出阶段
        AR["AgentResponse"]
        TRACE["message_trace"]
        PW["PersistenceWriter"]
    end

    U --> IB
    SP --> IB
    MEM --> IB
    SK --> IB
    IB --> MSGS
    MSGS --> TE
    TE -->|"有 tool_calls"| TC
    TC -->|"CapabilityFacade"| TR
    TR -->|"重新进入"| MSGS
    TE -->|"无 tool_calls"| AR
    AR --> TRACE
    TRACE --> PW
    AR -->|"content"| U

    style IB fill:#fff3e0,stroke:#e65100,color:#000
    style TE fill:#fff3e0,stroke:#e65100,color:#000
    style AR fill:#e8f5e9,stroke:#2e7d32,color:#000
    style PW fill:#e8f5e9,stroke:#2e7d32,color:#000
```

## 停止条件汇总

TurnEngine 循环在以下任一条件满足时终止：

| 停止条件 | StopReason | 触发时机 |
|---------|------------|---------|
| LLM 返回纯文本（无 tool_calls） | `COMPLETED` | 正常完成，最常见的情况 |
| 达到最大迭代次数 | `MAX_TURNS` | 迭代计数达到 `max_iterations`（默认 20） |
| 检测到重复工具调用 | `REPEATED_TOOL` | 连续两次迭代产生了完全相同的工具名称和参数 |
| 执行异常 | `ERROR` | LLM 调用或工具执行过程中抛出不可恢复异常 |
| 用户中止 | `USER_ABORTED` | 用户主动中断执行 |
| 工具审批被拒绝 | `APPROVAL_DENIED` | 需要用户审批的工具调用被拒绝 |
| 审批超时 | `APPROVAL_TIMEOUT` | 等待用户审批超时 |
| 需要用户输入 | `USER_INPUT_NEEDED` | 工具执行过程中需要用户补充信息 |

## message_trace 权威记录

`AgentResponse.message_trace` 是 TurnEngine 在一次执行中产生的所有消息的权威记录，按时间顺序排列，包含：

1. **assistant tool_call 消息**：LLM 请求调用工具时的 assistant 消息（`message_kind="assistant_tool_call"`）
2. **tool_result 消息**：工具执行结果（`message_kind="tool_result"`）
3. **最终 assistant 消息**：LLM 的最终文本回复（`message_kind="assistant_text"`）

每条 trace 消息都携带 `turn_id`、`iteration`、`provider`、`usage` 等元数据，用于持久化、日志记录和可观测性。
