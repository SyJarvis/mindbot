---
title: 交互式 Shell 命令
---

# 交互式 Shell 命令

通过 `mindbot shell` 进入交互式 Shell 后，你可以使用以下 slash 命令来控制对话过程。

## 进入 Shell

```bash
mindbot shell
```

## Slash 命令一览

| 命令 | 说明 |
|------|------|
| `/model` | 列出所有可用模型 |
| `/model <name>` | 切换到指定模型 |
| `/status` | 显示当前状态信息 |
| `/help` | 显示帮助信息 |
| `exit` | 退出 Shell |
| `quit` | 退出 Shell |
| `bye` | 退出 Shell |

## 使用示例

### 列出可用模型

```
You> /model
可用模型:
  1. local-ollama/qwen3
  2. local-ollama/qwen3-vl:8b
  3. moonshot/kimi-k2.5
```

### 切换模型

```
You> /model local-ollama/qwen3
已切换模型: local-ollama/qwen3
```

模型名称格式为 `instance_name/model_id`，与 `settings.json` 中 `providers` 的配置对应。

### 查看状态

```
You> /status
当前模型: local-ollama/qwen3
工作空间: ~/.mindbot/workspace
会话 ID: abc123
```

### 退出 Shell

输入以下任意一个命令即可退出：

```
You> exit
You> quit
You> bye
```

## 使用技巧

- 在 Shell 中输入普通文本即可与 Agent 对话，不需要任何前缀
- 使用 `/model` 切换模型后，后续对话将使用新模型
- 使用向上/向下方向键可以浏览历史输入记录（历史存储在 `~/.mindbot/history/`）
