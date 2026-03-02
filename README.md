# MindBot

[![Version](https://img.shields.io/badge/Version-0.2.0-blue.svg)](https://github.com/your-org/mindbot)
[![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

基于 **Python + asyncio** 的模块化 AI Agent 框架，支持多 Provider、动态路由、流式响应和工具确认机制。

**[📖 架构文档](docs/ARCHITECTURE.md) · [🧱 分层文档](docs/architecture/layers/README.md)**

## 特性

| 特性 | 说明 |
|------|------|
| 统一入口 | `AgentOrchestrator` 自主决策，无需预选模式 |
| 流式响应 | 实时事件流，用户可看到 Agent 思考过程 |
| 工具确认 | 基于 OpenClaw 的多级安全确认机制 |
| 智能路由 | 根据内容类型/复杂度/关键词自动选择模型 |
| 多 Provider | OpenAI / Ollama / Transformers / llama.cpp |
| 可中断执行 | 用户可随时中止 Agent 运行 |
| 记忆系统 | 短期/长期记忆，向量检索，自动归档 |
| 上下文管理 | Token 预算管理，自动压缩 |
| 多通道支持 | CLI、HTTP、飞书 |
| 对话追踪 | Tracer 记录完整对话日志 |

## 运行环境要求

| 要求 | 版本 |
|------|------|
| Python | >= 3.10 |
| asyncio | 内置 |

## 安装

```bash
git clone https://github.com/your-org/mindbot.git
cd mindbot
pip install -e .
```

## 快速开始

### 配置 LLM

**本地 Ollama（推荐）**

```bash
ollama pull qwen3
```

**云服务**

```bash
export OPENAI_API_KEY=your-api-key
# 或
export DEEPSEEK_API_KEY=your-api-key
```

### 创建配置文件

`~/.mindbot/settings.yaml`:

```yaml
agent:
  model: "ollama/0/qwen3"  # 格式：provider/endpoint_index/model
  temperature: 0.7
  max_tokens: 8192
  max_tool_iterations: 20

# Provider 配置 - 支持多 endpoint（多账号/负载均衡）
providers:
  # Ollama 本地模型
  ollama:
    strategy: "round-robin"  # round-robin | random | priority
    endpoints:
      - base_url: "http://localhost:11434"
        api_key: ""
        weight: 1
        models:
          - id: "qwen3"
            role: "chat"
            level: "medium"
            vision: false

  # OpenAI / 兼容服务
  openai:
    strategy: "round-robin"
    endpoints:
      - base_url: "https://api.openai.com/v1"
        api_key: "${OPENAI_API_KEY}"
        weight: 1
        models:
          - id: "gpt-4"
            role: "chat"
            level: "high"
            vision: true
          - id: "gpt-4-turbo"
            role: "chat"
            level: "high"
            vision: true

# 动态路由配置
routing:
  auto: true
  rules:
    - keywords: ["代码", "code", "编程", "函数", "算法"]
      level: "high"
      priority: 10
    - keywords: ["你好", "简单", "快"]
      level: "low"
      priority: 5

# 记忆配置
memory:
  storage_path: "~/.mindbot/data/memory.db"
  markdown_path: "~/.mindbot/data/memory"
  short_term_retention_days: 7

# 上下文配置
context:
  max_tokens: 8000
  compression: "truncate"

# 会话记录
session_journal:
  enabled: true
  path: "~/.mindbot/data/journal"

# 多模态配置
multimodal:
  max_images: 10
  max_file_size_mb: 20.0
```

### 基本使用

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

## CLI 命令

```bash
mindbot <command> [options]

Commands:
  generate-config  初始化默认配置（兼容别名: onboard）
  serve            启动服务（多通道）
  shell            进入交互式 shell
  chat             发送单条消息
  status      显示状态
  config show 显示当前配置

Options:
  -c, --config <path>   配置文件路径
  -v, --verbose         详细日志模式
  -h, --help            显示帮助
  --version             显示版本
```

## Examples

示例代码位于 `examples/`，建议直接运行文件（避免数字模块名导入问题）：

```bash
python examples/01_simple_chat.py
```

| 示例 | 说明 |
|------|------|
| `01_simple_chat.py` | 单轮对话 |
| `02_multi_turn.py` | 多轮会话与 `session_id` |
| `03_streaming.py` | 流式输出 |
| `04_event_callbacks.py` | 事件回调 |
| `05_system_prompt.py` | 系统提示词 |
| `06_tool_approval.py` | 工具审批 |
| `07_multi_agent.py` | 多 Agent 编排 |
| `08_config_from_code.py` | 纯代码配置 |
| `09_tool_whitelist.py` | 工具白名单 |
| `10_child_agent.py` | 子 Agent |
| `11_tool_example.py` | `@tool` 工具定义 |

## 架构

分层文档入口：[`docs/architecture/layers/README.md`](docs/architecture/layers/README.md)

统一执行流图（ASCII）：

```text
UserInput
   |
   v
[L1 Interface/Transport]
channels/* + bus/* + cli/*
   |
   v
[L2 Application/Orchestration]
MindBot.chat() -> Agent/MindAgent -> Scheduler.assemble()
   |
   v
[L3 Conversation Domain]
context manager/models/compression
   |
   v
[L5 Provider Adapters]
providers/* (LLM inference)
   |
   +--> if tool_calls --> [L2 Approval] --> [L4 Capability Tool Executor]
   |                                           capability/backends/tooling/*
   v
[L2 Commit]
Scheduler.commit() + memory append
   |
   v
AssistantResponse
```

## 核心模块

| 模块 | 路径 | 说明 |
|------|------|------|
| Bot | `bot.py` | 对外主入口 |
| Agent | `agent/` | 核心执行引擎 |
| Provider | `providers/` | LLM 提供商抽象 |
| Routing | `routing/` | 智能模型路由 |
| Context | `context/` | 上下文管理 |
| Memory | `memory/` | 记忆系统 |
| Capability Tooling | `capability/backends/tooling/` | 工具注册与执行 |
| Channels | `channels/` | 多通道支持 |
| Config | `config/` | 配置管理 |
| Session | `session/` | 会话日志与类型 |

## Agent 子系统

| 组件 | 文件 | 说明 |
|------|------|------|
| `MindBot` | `bot.py` | 用户侧统一 API |
| `MindAgent` | `agent/core.py` | Supervisor（主 Agent + 子 Agent 管理） |
| `Agent` | `agent/agent.py` | 基础会话执行单元 |
| `AgentOrchestrator` | `agent/orchestrator.py` | LLM + tool loop 编排 |
| `Scheduler` | `agent/scheduler.py` | assemble/commit 回合消息 |
| `StreamingExecutor` | `agent/streaming.py` | 流式与带工具调用执行 |
| `ApprovalManager` | `agent/approval.py` | 工具审批与白名单 |

## 智能路由

### 路由优先级

1. **媒体规则** - 包含图片 → 选择 vision 模型
2. **关键词规则** - 按优先级匹配用户输入
3. **复杂度评分** - 自动分析文本特征
4. **默认模型** - `agent.model` 配置

### 配置示例

```yaml
routing:
  auto: true
  rules:
    - keywords: [代码, code, 函数]
      level: high
      priority: 10

    - keywords: [天气, time]
      level: low
      priority: 5

providers:
  deepseek:
    base_url: https://api.deepseek.com/v1
    api_key: ${DEEPSEEK_API_KEY}
    models:
      - id: deepseek-chat
        level: medium
      - id: deepseek-reasoner
        level: high
```

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

```yaml
agent:
  approval:
    security: allowlist
    ask: on_miss
    timeout: 300
    whitelist:
      calculator: [".*"]
      search: [".*"]
    dangerous_tools:
      - delete_file
      - shell
      - execute_command
```

## LLM Provider

### 模型格式

`provider/model`（如 `ollama/qwen3`、`openai/gpt-4`）

### Ollama（本地）

```yaml
providers:
  ollama:
    base_url: http://localhost:11434/v1
    models: [qwen3, qwen3-vl]
```

### OpenAI / 兼容服务

```yaml
providers:
  openai:
    base_url: https://api.openai.com/v1
    api_key: ${OPENAI_API_KEY}
    models: [gpt-4, gpt-4-turbo]

  deepseek:
    base_url: https://api.deepseek.com/v1
    api_key: ${DEEPSEEK_API_KEY}
    models: [deepseek-chat, deepseek-reasoner]
```

### 多端点配置（负载均衡/故障转移）

```yaml
providers:
  openai:
    strategy: round-robin  # round-robin | random | priority
    endpoints:
      - base_url: https://api.openai.com/v1
        api_key: sk-key1
        weight: 2
        models:
          - id: gpt-4
            level: high
      - base_url: https://api.backup.com/v1
        api_key: sk-key2
        weight: 1
        models:
          - id: gpt-4
            level: high
```

## 数据目录

```
~/.mindbot/
├── settings.yaml         # 用户配置
├── data/
│   ├── memory.db         # 记忆数据库
│   └── memory/           # Markdown 记忆存储
├── logs/                 # 日志文件
└── sessions/             # 会话存储
```

## 项目结构

```
mindbot/
├── src/mindbot/
│   ├── bot.py            # 对外主入口 MindBot
│   ├── agent/            # Agent 编排与执行
│   ├── context/          # 上下文与消息模型
│   ├── memory/           # 记忆系统
│   ├── capability/       # 能力层（含 tooling backend）
│   ├── providers/        # LLM 提供商适配
│   ├── routing/          # 模型路由
│   ├── channels/         # CLI / HTTP / Feishu
│   ├── bus/              # 消息总线
│   ├── session/          # 会话存储与类型
│   ├── generation/       # 动态工具生成
│   ├── builders/         # 构建器
│   ├── multimodal/       # 多模态支持
│   ├── cron/             # 定时任务
│   ├── config/           # 配置模型与加载
│   └── cli/              # CLI 命令实现
├── docs/                 # 文档
├── tests/                # 测试
└── pyproject.toml        # 项目配置
```

## 通道配置

### 飞书

```yaml
channels:
  feishu:
    enabled: true
    app_id: cli_xxx
    app_secret: xxx
    encrypt_key: xxx
    verification_token: xxx
```

### HTTP

```yaml
channels:
  http:
    enabled: true
    host: 0.0.0.0
    port: 31211
```

## License

MIT
