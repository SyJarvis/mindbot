---
id: DEV-024
type: develop
status: done
created: 2026-05-30
updated: 2026-05-30
related: DEV-022
---

# Runtime Session Protocol Bus

## 背景

`DEV-022` 已经统一了 turn 内部执行路径，但 MindBot 的消息入口仍然分散：

- TUI shell 直接调用 `MindBot.chat(..., on_event=...)`
- one-shot CLI 直接调用 `MindBot.chat()`
- Feishu / CLIChannel / 部分 HTTP 通过 `MessageBus -> ChannelManager -> MindBot.chat()`
- HTTP stream 直接调用 `MindBot.chat_stream()`

这说明当前统一的是 `TurnEngine`，不是更外层的 runtime protocol bus。参考 Codex 的 `Submission(Op)` / `Event(EventMsg)` 设计，本 DEV 只实现前三步：建立轻量 `RuntimeSession`，迁移 TUI，迁移 HTTP/channel adapter 中的可控入口。

## 实现方案

第一阶段：新增轻量 runtime protocol bus

1. 新增 `RuntimeOp`，先支持：
   - `UserTurn`
   - `Interrupt`
   - `UserInputAnswer`
   - `PendingUserInput`
2. 新增 `RuntimeEvent`，复用 `AgentEvent` 作为 payload，并保留：
   - `op_id`
   - `type`
   - `data`
3. 新增 `RuntimeSession`：
   - `submit(op) -> op_id`
   - `next_event() -> RuntimeEvent`
   - 内部先包装现有 `MindBot.chat(..., on_event=...)`
4. 不改 `TurnEngine` 语义，不引入权限/工具确认统一。

第二阶段：TUI shell 迁移到 RuntimeSession

1. Shell 不再自己创建 `Wire` 包装 `bot.chat()`。
2. Shell 通过 `RuntimeSession.submit(UserTurn)` 启动 turn。
3. Shell 通过 `RuntimeSession.next_event()` 消费事件。
4. 运行中输入：
   - pending request 优先提交 `UserInputAnswer`
   - 普通输入提交 `PendingUserInput`
5. 保持现有 TUI 行为不变。

第三阶段：迁移 HTTP/channel adapter 的可控入口

1. HTTP stream 从 `bot.chat_stream()` 改为 `RuntimeSession` 事件消费并输出 SSE delta。
2. 普通 HTTP / Feishu / CLIChannel 先保留最终回复路径，但通过统一 helper 使用 `RuntimeSession` 聚合 final response。
3. `ChannelManager` 的 inbound chat handler 可接收 runtime-backed handler。

## 实现记录

- [x] 新增 runtime protocol 数据结构
- [x] 新增 `RuntimeSession`
- [x] 补 `RuntimeSession` 基础测试
- [x] TUI shell 迁移到 `RuntimeSession`
- [x] 补 TUI runtime session 测试
- [x] HTTP stream 迁移到 `RuntimeSession`
- [x] 普通 channel 路径提供 runtime-backed handler
- [x] 移除 Feishu media-only outbound 的多余空卡片发送
- [x] 运行相关测试

## 验证

- [x] `pytest tests/runtime/test_session.py tests/cli/test_tui.py tests/channels tests/agent/test_turn_engine.py tests/agent/test_session_journal_integration.py` — 53 passed
