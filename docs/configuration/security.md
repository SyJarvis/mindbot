# 安全配置

MindBot 提供多层安全机制：工具确认审批、路径安全策略、工作空间隔离。

## 工具确认机制

### 安全级别

| 级别 | 说明 |
|------|------|
| `DENY` | 所有工具被拒绝 |
| `ALLOWLIST` | 白名单工具自动批准，其他根据 `ask` 参数 |
| `FULL` | 所有工具可访问，根据 `ask` 参数决定 |

### 确认模式

| 模式 | 说明 |
|------|------|
| `OFF` | 从不请求确认 |
| `ON_MISS` | 白名单外请求确认 |
| `ALWAYS` | 总是请求确认 |

### 配置示例

```jsonc
{
  "agent": {
    "approval": {
      "security": "allowlist",
      "ask": "on_miss",
      "timeout": 300,
      "whitelist": {
        "calculator": [".*"],
        "search": [".*"]
      },
      "dangerous_tools": [
        "delete_file",
        "shell",
        "execute_command"
      ]
    }
  }
}
```

### 字段说明

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `security` | string | `allowlist` | 安全级别 |
| `ask` | string | `off` | 确认模式 |
| `timeout` | int | 300 | 审批超时（秒） |
| `whitelist` | object | `{}` | 工具名到参数正则的映射 |
| `dangerous_tools` | array | `[]` | 标记为危险的工具列表 |

## 路径安全策略

MindBot v0.3 将“文件路径策略”和“Shell 执行边界”分开描述：

```jsonc
{
  "agent": {
    "workspace": "~/.mindbot/workspace",
    "system_path_whitelist": ["~/.mindbot", "/tmp"],
    "trusted_paths": ["/root/research/mindbot"],
    "restrict_to_workspace": true,
    "shell_execution": {
      "policy": "cwd_guard",
      "sandbox_provider": "none",
      "fail_if_unavailable": false
    }
  }
}
```

### 文件路径策略

- **workspace**: 默认工作目录，所有相对路径以此解析
- **restrict_to_workspace**: 启用时，文件工具只能在 `workspace` 和白名单定义的允许根目录内运行
- **system_path_whitelist**: 额外允许访问的系统路径根目录列表，每个根目录都会递归覆盖其子目录和文件
- **trusted_paths**: 用户显式授权过的目录根；shell 会话在这些目录启动后可把它们作为默认当前目录

### Shell 执行边界

- **shell_execution.policy**: Shell 的独立执行策略；默认 `cwd_guard`
- **cwd_guard**: 只校验 `working_dir` 是否落在允许根目录内，并应用轻量危险命令检查
- **sandboxed**: 预留给未来 OS-level sandbox，v0.3 尚未提供
- **shell_execution.sandbox_provider**: 预留的沙箱后端，例如未来的 `bubblewrap`
- **shell_execution.fail_if_unavailable**: 未来 `sandboxed` 模式下，沙箱不可用时是否失败关闭

### 安全规则

- 绝对路径必须落在允许范围内
- 相对路径基于 workspace 解析
- 允许根目录按目录树递归生效
- shell 启动目录不是自动授权目录；首次进入未信任目录时需要用户显式确认
- 文件工具的路径策略适用于读、写、编辑、列目录等内置文件操作
- Shell 的 `cwd_guard` 不是 OS 级文件系统沙箱；shell 子进程不会自动获得强隔离
- 超出范围的路径返回策略错误
- 环境变量替换在路径检查前执行

## 工具持久化策略

工具执行产生的中间消息可以按不同策略保留到上下文中：

| 策略 | 行为 | Token 消耗 |
|------|------|-----------|
| `none` | 不保留工具中间消息 | 最低 |
| `summary` | 压缩为一条 `[Tool usage summary]` 消息 | 低 |
| `full` | 保留所有 assistant+tool_calls 和 tool results | 最高 |

```jsonc
{
  "agent": {
    "tool_persistence": "summary"
  }
}
```
