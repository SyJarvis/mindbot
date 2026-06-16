---
id: DEV-022
type: develop
status: done
created: 2026-05-30
updated: 2026-05-30
---

# Codex-lite Event Runtime

## 背景

当前 MindBot 的 turn 执行有两条路径：

- `chat()` 通过 `TurnEngine.run()` 执行并聚合 `AgentResponse`
- `chat_stream()` 通过 `TurnEngine.run_stream()` 执行，但实际先收集完整 LLM 响应，再回放 chunk

CLI/TUI 为了获得真正的流式输出，绕过 `chat_stream()`，使用 `chat(..., on_event=...)`。这导致 API、CLI、测试各自理解一部分执行状态，后续要支持同一 turn 内暂停/继续会继续变复杂。

参考 Codex 的事件驱动设计，但不照搬其 legacy/app-server/rollout 复杂层。目标是建立 MindBot 自己的轻量事件 runtime。

## 实现方案

第一阶段：

1. 在 `TurnEngine` 内新增统一事件流执行入口，作为 `run()` 和 `run_stream()` 的共同底层。
2. 事件仍沿用现有 `AgentEvent`，避免一次性扩大改动面。
3. `run()` 消费事件流并聚合 `AgentResponse`。
4. `run_stream()` 消费同一事件流，只向调用方 yield `DELTA` 文本。
5. 保持 `message_trace`、turn record、persistence 行为不变。
6. 增加测试证明 `run_stream()` 在最终回答阶段是真实时 yield，而不是结束后回放。

第二阶段：

1. 为 `TurnEngine` 增加 `on_user_input_request` resolver。
2. 将 `task_progress_policy="ask"` 在有 resolver 时改成同 turn 内 awaitable request。
3. CLI 将运行中 turn 的下一条输入路由为 request answer。

第三阶段：

1. 为 `TurnEngine` 增加 `on_pending_user_input` drain hook。
2. 工具执行完成后、下一次 LLM 采样前，将用户运行中追加输入写入同一 turn 的 message trace。
3. CLI 在 turn 运行中收到普通输入时先入队，不启动并发 turn。
4. 如果输入发生在最终回复阶段、没有下一次采样机会，CLI 在当前 turn 完成后按队列顺序启动后续 turn。

第四阶段：

1. `AgentEvent` 增加顶层 `turn_id` / `seq` 字段，作为轻量稳定事件协议。
2. `TurnEngine.run_events()` 统一为所有运行时事件打上同一个 `turn_id`。
3. `TurnEngine.run_events()` 按事件发出顺序分配递增 `seq`，包括工具事件、用户输入 request/received、complete/error。

后续阶段：

1. 将 request-answer 抽象推广到权限申请、工具确认等交互。
2. 引入更正式的 `ActiveTurn` 对象，集中管理 cancel、pending input、request resolver、状态快照。

## 实现记录

- [x] 新增统一事件流执行入口
- [x] `run()` 改为聚合事件流
- [x] `run_stream()` 改为过滤事件流中的 DELTA
- [x] 补流式时序测试
- [x] `ask` 策略支持 resolver 并在同一 turn 内继续
- [x] CLI 运行中输入可 resolve pending user-input request
- [x] `TurnEngine` 支持在采样轮次之间 drain pending user input
- [x] CLI 运行中普通输入进入队列，避免并发 turn
- [x] 最终回复阶段残留队列按顺序转为后续 turn
- [x] `AgentEvent` 支持顶层 `turn_id` / `seq`
- [x] `TurnEngine.run_events()` 为事件统一分配 runtime ordering metadata
- [x] 运行 agent/CLI 相关测试

## 验证

- [x] `pytest tests/agent/test_turn_engine.py tests/cli/test_tui.py tests/agent/test_session_journal_integration.py` — 43 passed
