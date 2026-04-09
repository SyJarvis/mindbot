---
title: 快速开始
---

# 快速开始

本节将引导你在五步之内完成 MindBot 的首次配置并运行第一个对话。

## 第 1 步：配置 LLM

MindBot 支持本地 Ollama 和云端 API 两种方式接入大语言模型。

### 本地 Ollama（推荐）

安装并启动 [Ollama](https://ollama.com/)，然后拉取模型：

```bash
ollama pull qwen3
```

### 云服务

通过环境变量配置 API 密钥：

```bash
export OPENAI_API_KEY=your-api-key
# 或
export MOONSHOT_API_KEY=your-api-key
```

## 第 2 步：初始化配置

```bash
mindbot generate-config
```

这会在 `~/.mindbot/` 下生成 `settings.json` 和 `SYSTEM.md`。

## 第 3 步：编辑配置文件

编辑 `~/.mindbot/settings.json`（JSONC 格式，支持注释和尾随逗号）。以下是完整配置示例：

```jsonc
{
  // Provider 实例 - 支持多账号、负载均衡
  "providers": {
    // 本地 Ollama 实例
    "local-ollama": {
      "type": "ollama",
      "strategy": "round-robin",
      "endpoints": [
        {
          "base_url": "http://localhost:11434",
          "weight": 1,
          "models": [
            { "id": "qwen3", "role": "chat", "level": "medium", "vision": false },
            { "id": "qwen3-vl:8b", "role": "chat", "level": "high", "vision": true }
          ]
        }
      ]
    },

    // Moonshot（OpenAI 兼容）
    "moonshot": {
      "type": "openai",
      "strategy": "priority",
      "endpoints": [
        {
          "base_url": "https://api.moonshot.cn/v1",
          "api_key": "{env:MOONSHOT_API_KEY}",
          "weight": 1,
          "models": [
            { "id": "kimi-k2.5", "role": "chat", "level": "high", "vision": true }
          ]
        }
      ]
    }
  },

  // 默认模型: "instance_name/model_id"
  "agent": {
    "model": "local-ollama/qwen3",
    "temperature": 0.7,
    "max_tokens": 8192,
    "max_tool_iterations": 20,
    "workspace": "~/.mindbot/workspace",
    "system_path_whitelist": ["~/.mindbot"],
    "trusted_paths": [],
    "restrict_to_workspace": true,
    "shell_execution": {
      "policy": "cwd_guard",
      "sandbox_provider": "none",
      "fail_if_unavailable": false
    },
    "tool_persistence": "none"
  },

  // 动态路由
  "routing": {
    "auto": true,
    "rules": [
      { "keywords": ["代码", "code", "编程"], "level": "high", "priority": 10 },
      { "keywords": ["你好", "简单"], "level": "low", "priority": 5 }
    ]
  },

  // 记忆配置
  "memory": {
    "storage_path": "~/.mindbot/data/memory.db",
    "markdown_path": "~/.mindbot/data/memory",
    "short_term_retention_days": 7
  },

  // Prompt-layer skills
  "skills": {
    "enabled": true,
    "skill_dirs": [],
    "always_include": ["mindbot-self-knowledge"],
    "max_visible": 8,
    "max_detail_load": 2,
    "trigger_mode": "metadata-match"
  },

  // 上下文配置
  "context": {
    "max_tokens": 8000,
    "compression": "truncate",
    "blocks": {
      "skills_overview": 640,
      "skills_detail": 1200
    }
  },

  // 会话记录
  "session_journal": {
    "enabled": true,
    "path": "~/.mindbot/data/journal"
  },

  // 多模态配置
  "multimodal": {
    "max_images": 10,
    "max_file_size_mb": 20.0
  },

  // 通道配置
  "channels": {
    "http": { "enabled": false, "host": "0.0.0.0", "port": 31211 },
    "cli": { "enabled": false },
    "feishu": { "enabled": false, "app_id": "", "app_secret": "" },
    "telegram": { "enabled": false, "token": "" }
  }
}
```

### Agent 配置项说明

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `model` | string | `"local-ollama/qwen3.5:2b"` | 默认模型，格式 `instance/model` |
| `workspace` | string | `"~/.mindbot/workspace"` | 内置文件/Shell 工具的工作空间根目录 |
| `system_path_whitelist` | list | `["~/.mindbot"]` | 额外允许的系统路径根目录白名单，目录树会递归放行 |
| `trusted_paths` | list | `[]` | 用户显式信任的目录根；shell 会话可在授权后把这些目录当作默认当前目录 |
| `restrict_to_workspace` | bool | `true` | 是否将工具限制在工作空间和允许根目录内 |
| `shell_execution.policy` | string | `"cwd_guard"` | Shell 执行策略；v0.3 默认只做 `working_dir` 与危险命令检查 |
| `shell_execution.sandbox_provider` | string | `"none"` | 预留的 Shell 沙箱后端 |
| `shell_execution.fail_if_unavailable` | bool | `false` | 未来 `sandboxed` 模式下，沙箱不可用时是否失败关闭 |
| `tool_persistence` | string | `"none"` | 工具消息持久化策略：`none` / `summary` / `full` |
| `max_tool_iterations` | int | `20` | 单轮最大工具迭代次数 |
| `temperature` | float | `0.7` | LLM 温度参数 |
| `max_tokens` | int | `8192` | 最大生成 token 数 |

## 第 4 步：验证配置

```bash
mindbot config validate
```

验证通过后即可开始使用。如果配置有误，命令会输出具体的错误信息。

## 第 5 步：基本使用

```python
import asyncio
from mindbot import MindBot


async def main():
    bot = MindBot()

    # 简单对话
    response = await bot.chat(
        "你好，请介绍一下自己",
        session_id="user123",
    )
    print(response.content)

    # 带工具事件回调
    response = await bot.chat(
        "帮我计算 25 * 37",
        session_id="user123",
        on_event=lambda e: print(f"[{e.type}] {e.data}"),
    )
    print(response.content)


asyncio.run(main())
```

## 下一步

- [CLI 命令参考](cli-reference.md) -- 了解所有命令行命令
- [交互式 Shell 命令](shell-commands.md) -- 学习 Shell 模式的交互命令
- [示例代码](examples.md) -- 通过 11 个示例深入学习
- [多 Agent 编排](multi-agent.md) -- 构建多 Agent 协作系统
- [Skills 机制](skills.md) -- 了解技能包的创建与配置
