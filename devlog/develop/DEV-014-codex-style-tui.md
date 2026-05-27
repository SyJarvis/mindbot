---
id: DEV-014
type: develop
status: done
created: 2026-05-27
updated: 2026-05-27
---

# Codex 风格 TUI 交互重构

## 背景

当前全屏 TUI 已能固定显示消息区、输入区和状态栏，但交互仍偏基础：输入框为单行，消息事件缺少稳定的角色结构，底部 composer 与 Codex CLI 的使用体验还有差距。

## 实现方案

保持 `TuiApp` 对外接口不变，集中重构 `src/mindbot/cli/shell/tui.py`：

1. 固定底部 composer：输入框加上 Codex 风格边框，支持多行输入，`Enter` 提交，`Esc+Enter` 换行。
2. 改进消息流：用户、助手、thinking、工具调用、错误和 turn summary 使用更清晰的前缀与样式。
3. 保留现有状态栏：继续复用 `render_toolbar()`，避免重复实现 git/context/tips 逻辑。

## 实现记录

- [x] 重构 TUI 布局和输入 composer
- [x] 改进消息和工具事件渲染
- [x] 添加轻量测试并验证

## 验证

- [x] TUI 逻辑测试通过
- [x] `tui.py` 可编译
