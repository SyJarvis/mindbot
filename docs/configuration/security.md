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

MindBot 内置的文件和 Shell 工具采用**工作空间隔离**机制：

```jsonc
{
  "agent": {
    "workspace": "~/.mindbot/workspace",
    "system_path_whitelist": ["~/.mindbot", "/tmp"],
    "restrict_to_workspace": true
  }
}
```

### 工作空间隔离

- **workspace**: 默认工作目录，所有相对路径以此解析
- **restrict_to_workspace**: 启用时，工具只能访问 workspace 和白名单中的路径
- **system_path_whitelist**: 额外允许访问的系统路径列表

### 安全规则

- 绝对路径必须落在允许范围内
- 相对路径基于 workspace 解析
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
