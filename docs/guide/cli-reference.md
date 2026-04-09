---
title: CLI 命令参考
---

# CLI 命令参考

MindBot 提供了一组命令行工具，用于配置管理、服务启动和交互式对话。

## 基本语法

```bash
mindbot <command> [options]
```

## 命令一览

| 命令 | 说明 |
|------|------|
| `mindbot generate-config` | 初始化默认配置（别名: `onboard`） |
| `mindbot serve` | 启动服务（多通道） |
| `mindbot toolcall15-adapter` | 启动 ToolCall-15 的 OpenAI-compatible 适配器 |
| `mindbot shell` | 进入交互式 Shell |
| `mindbot chat` | 发送单条消息 |
| `mindbot status` | 显示状态 |
| `mindbot config show` | 显示当前配置 |
| `mindbot config validate` | 验证配置 |
| `mindbot config migrate` | 将 YAML 配置迁移到 JSON |

## 全局选项

| 选项 | 说明 |
|------|------|
| `-c, --config <path>` | 指定配置文件路径 |
| `-v, --verbose` | 详细日志模式 |
| `-h, --help` | 显示帮助 |
| `--version` | 显示版本 |

## 命令详解

### generate-config

初始化默认配置文件。首次使用 MindBot 时必须执行此命令。

```bash
# 创建默认配置到 ~/.mindbot/settings.json
mindbot generate-config

# 使用别名
mindbot onboard

# 指定配置文件路径
mindbot generate-config -c /path/to/settings.json
```

### serve

启动 MindBot 服务，支持多通道（CLI、HTTP、飞书、Telegram）。具体启用哪些通道由 `settings.json` 中的 `channels` 配置决定。

```bash
# 启动所有已启用的通道
mindbot serve

# 启用详细日志
mindbot serve -v
```

### shell

进入 MindBot 交互式 Shell，可以与 Agent 进行连续对话。Shell 中支持 slash 命令（详见 [交互式 Shell 命令](shell-commands.md)）。

```bash
mindbot shell
```

### toolcall15-adapter

启动一个最小的 OpenAI-compatible `/v1/chat/completions` 适配器，供 `benchmark/ToolCall-15` 调用。

```bash
mindbot toolcall15-adapter --host 127.0.0.1 --port 11435 --model local-ollama/qwen3
```

常见用法：

```bash
# 使用默认 ~/.mindbot/settings.json
mindbot toolcall15-adapter --model local-ollama/qwen3

# 指定配置文件
mindbot toolcall15-adapter --config-path /path/to/settings.json --model moonshot/kimi-k2.5
```

### chat

发送单条消息给 Agent 并获取回复，适合脚本调用或快速测试。

```bash
mindbot chat "你好，请介绍一下自己"
```

### status

显示 MindBot 当前运行状态，包括 Provider 连接状态、模型信息等。

```bash
mindbot status
```

### config show

显示当前加载的完整配置信息。

```bash
mindbot config show
```

### config validate

验证配置文件的格式和内容是否正确。

```bash
mindbot config validate

# 验证指定配置文件
mindbot config validate -c /path/to/settings.json
```

### config migrate

将旧版 YAML 格式的配置文件迁移到 JSON/JSONC 格式。

```bash
mindbot config migrate
```

> **注意**：YAML 配置格式已弃用，建议尽快完成迁移。
