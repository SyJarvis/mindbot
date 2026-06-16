---
id: DEV-021
type: develop
status: done
created: 2026-05-29
updated: 2026-06-08
---

# TUI 流式输出重复 & 工具循环策略断裂修复

## 背景

两个独立 bug 同时暴露：

1. **TUI 流式输出重复**：agent turn 中多轮迭代（LLM + 工具）时，之前迭代的文本在
   下一轮迭代中被重复显示。
2. **工具循环策略断裂**：`task_progress_policy="ask"` 在达到迭代阈值后发出
   `USER_INPUT_REQUEST` 事件，但 TUI 不处理该事件，效果等同于 `"stop"`。

## 根因分析

### Bug 1：`_TuiTextState.pending_line` 跨迭代未清理

`_handle_tui_event` 在 THINKING / TOOL_EXECUTING 时调用 `tui.finalize_delta()`
将 streaming 行转为 normal 行，但没有清理 `text_buffer.pending_line`。下一轮
迭代的 DELTA 事件将新文本追加到旧的 `pending_line` 上，`upsert_delta` 显示
旧文本+新文本的混合体。

### Bug 2：策略断裂（3 个断裂点）

- **断裂 1**：`_handle_tui_event` 没有 `USER_INPUT_REQUEST` 分支，事件被丢弃
- **断裂 2**：TurnEngine 在 `USER_INPUT_NEEDED` / `REPEATED_TOOL` 时不触发 COMPLETE
  事件，TUI 无法收到 turn 结束信号
- **断裂 3**：没有暂停-恢复机制，turn 结束后无法在同一 turn 内继续
- **附带**：`LoopConfig` 死代码（`agent/models.py`）误导读者，实际控制逻辑在
  `AgentConfig` + `TurnEngine` 参数中

## 已完成修复

- [x] `shell/__init__.py`：所有 `finalize_delta()` 处同步 `clear_pending_line()`
- [x] `turn_engine.py`：`run()` 统一 COMPLETE 触发（所有非 ERROR stop reason）
- [x] `turn_engine.py`：`run_stream()` 同上
- [x] `shell/__init__.py`：`_handle_tui_event` 增加 `USER_INPUT_REQUEST` 分支
- [x] `tui.py`：新增 `append_review_prompt` / `add_review_prompt` + `review-prompt` 样式
- [x] `agent/models.py` + `agent/__init__.py`：删除 `LoopConfig` 死代码
- [x] 测试通过（202 passed，唯一失败的 feishu 测试为已有问题）

## 待做（增强项）收口结论

### TODO-1：真正的暂停-恢复语义

已由 `DEV-022` + `DEV-023` 覆盖为同一 turn 内 request-answer：

- `TurnEngine.run_events()` 在 task progress review 时发出统一 runtime request。
- `RuntimeSession` 持有 pending request future。
- TUI 提交时优先解析 pending request，再处理普通 pending input queue。

### TODO-2：默认值不一致防御

已修复：`Agent` / `TurnEngine` 构造器默认值与 config schema 对齐为：

| 参数 | 默认 |
|---|---|
| `task_progress_policy` | `"ask"` |
| `task_progress_review_after` | `15` |

## 验证

- `pytest tests/agent/test_turn_engine.py` — 10 passed
- `pytest tests/` — 202 passed
- `pytest tests/agent/test_turn_engine.py tests/runtime/test_session.py tests/cli/test_tui.py -q` — 40 passed
