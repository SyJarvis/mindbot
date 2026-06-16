---
id: DEV-023
type: develop
status: done
created: 2026-05-30
updated: 2026-06-08
related: DEV-022
---

# Runtime Request-Answer Unification

## 背景

`DEV-022` 已经建立 Codex-lite 事件 runtime：

- `TurnEngine.run_events()` 作为统一事件流入口
- `chat()` / `chat_stream()` 共享同一执行路径
- TUI 支持真正流式输出
- `task_progress_policy="ask"` 支持同一 turn 内 request-answer
- 运行中普通输入可进入 pending input queue
- `AgentEvent` 已具备顶层 `turn_id` / `seq`

但当前交互式 request 仍然分散：

- `USER_INPUT_REQUEST` 由 `TurnEngine` 的 `on_user_input_request` 单独处理
- `PERMISSION_REQUEST` 由 permission manager / CLI 相关路径处理
- `TOOL_CALL_REQUEST` 事件模型存在，但工具确认与执行路径还未统一成同一套 resolver

继续扩展时，如果每种 request 都各自维护 pending 状态，TUI、CLI、权限、工具执行之间会重新出现重复状态机。

## 实现方案

第一阶段：梳理现状，不改行为

1. 找出现有 request 类事件的生产点与消费点。
2. 明确哪些 request 当前会阻塞 turn，哪些只是事件通知。
3. 确认 permission manager 与 tool execution 的同步/异步边界。

结论：

- 当前真正阻塞 turn 的 request 是 `USER_INPUT_REQUEST`，由 task progress review 触发。
- `PERMISSION_REQUEST` 由 permission manager 独立生产和解析，不在本轮强行迁移。
- `TOOL_CALL_REQUEST` 是事件模型能力，当前工具执行主路径仍通过 capability facade，不在本轮接入。

第二阶段：定义最小统一接口

1. 增加统一的 runtime request 数据结构，表达：
   - `request_id`
   - request 类型
   - 展示给用户的 prompt
   - 可选 choices / metadata
2. 增加统一 resolver 类型：`on_runtime_request(request) -> answer`。
3. 保留 `on_user_input_request` 作为兼容适配层，内部转成统一 request。

第三阶段：接入最小链路

1. 先将 `USER_INPUT_REQUEST` 改为使用统一 resolver。
2. CLI/TUI 只维护一个 pending request future。
3. 保持现有 `task_progress_policy="ask"` 行为不变。
4. 补测试覆盖：
   - request event 带 `turn_id` / `seq`
   - resolver answer 写入同一 turn message trace
   - CLI 对 pending request 的提交仍优先于 pending input queue

第四阶段：扩展到权限/工具确认

本阶段推迟到 ACP 前置评估之后再做。原因是权限/工具确认与 ACP 的
`session/request_permission` 语义相关，过早迁移会增加返工风险。

## 实现记录

- [x] 梳理 request 类事件生产点与消费点
- [x] 定义统一 runtime request / resolver 接口
- [x] 将 `USER_INPUT_REQUEST` 接入统一 resolver
- [x] 保持 CLI pending request 优先级
- [x] 补 request-answer 行为测试
- [x] 更新验证记录

## 验证

- [x] `pytest tests/agent/test_turn_engine.py tests/runtime/test_session.py tests/cli/test_tui.py -q` — 40 passed
- [ ] 如接入权限/工具确认，补充对应 permission/tool 测试
