---
id: DEV-020
type: develop
status: done
created: 2026-05-29
updated: 2026-05-29
---

# Default Full Permission

## 背景

当前阶段先不重新设计 MindBot 安全策略。为了降低使用门槛，默认策略临时调整为
完全权限：工具默认可用、不主动询问审批，内置文件和 Shell 工具默认不限制在
workspace 根目录内。

## 实现方案

将配置默认值调整为：

- `agent.approval.security = "full"`
- `agent.approval.ask = "off"`
- `agent.restrict_to_workspace = false`
- `agent.shell_execution.block_dangerous_commands = false`

显式配置仍然可以恢复 allowlist 和 workspace 限制。

## 实现记录

- [x] 更新配置 schema 默认值
- [x] 增加默认完全权限回归测试
- [x] 验证显式限制配置仍生效
- [x] 将 Shell 危险命令拦截改为可配置且默认关闭
- [x] 同步配置文档中的默认值

## 验证

- [x] `pytest tests/config/test_security_defaults.py tests/builders/test_agent_builder_workspace.py tests/tools/test_builtin_tools.py tests/tools/test_mindbot_ops.py`
