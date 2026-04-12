# MindBot

<div align="center">
  <img src="docs/assets/mindbot_logo.png" alt="MindBot" width="400" />
</div>

<p align="center">
  <a href="https://github.com/SyJarvis/mindbot"><img src="https://img.shields.io/badge/Version-0.3.3-blue.svg" alt="Version"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.10+-blue?logo=python" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License"></a>
</p>

<p align="center">基于 <strong>Python + asyncio</strong> 的模块化 AI Agent 框架，支持多 Provider、动态路由、流式响应和工具确认机制。</p>

<p align="center"><a href="docs/index.md">📖 文档</a> · <a href="docs/guide/quickstart.md">🚀 快速开始</a> · <a href="docs/architecture/overview.md">🧱 架构</a> · <a href="docs/guide/examples.md">📝 示例</a></p>

---

## 📢 News

- **2026-04-10** 🚀 **实时配置系统** — ConfigBus 事件总线、AuthManager 授权管理、配置持久化、多实例同步
- **2026-04-09** 🏗️ **ACP 协议支持** — Agent Client Protocol 通道，支持 Claude Code、Codex 等外部 Agent
- **2026-04-02** 📊 **Agent Benchmark** — ToolCall-15 和 Real-Tools benchmark 框架

<details>
<summary>Earlier news</summary>

- **2026-03-05** 🔧 **v0.3.0** — 多 Agent 编排、Skills 机制、会话 Journal
- **2026-02-27** 🧠 **记忆系统** — 短期/长期记忆，向量检索
- **2026-02-20** 💬 **多通道支持** — 飞书、Telegram、HTTP
- **2026-02-10** 🎉 **MindBot 发布** — 基于 Python + asyncio 的模块化 Agent 框架

</details>

---

## 特性

- 🪶 **轻量高效** — 纯 Python + asyncio，五层架构设计
- 🧠 **长期记忆** — Markdown 存储，向量检索，自动归档
- 🎯 **智能路由** — 根据内容类型/复杂度/关键词自动选择模型
- 🔒 **工具确认** — 多级安全确认机制（白名单、危险工具检测）
- 🛡️ **路径安全** — 文件工具路径策略 + Shell 执行边界控制
- 💬 **多通道** — CLI、HTTP、飞书、Telegram
- 🔌 **Skills 机制** — `SKILL.md` 技能包按需注入 prompt
- ⚙️ **实时配置** — ConfigBus 热更新，授权实时生效

---

## 安装

```bash
git clone https://github.com/SyJarvis/mindbot.git
cd mindbot
pip install -e .
```

---

## 快速开始

### 1. 配置 LLM

MindBot 支持四种 LLM 适配器：

| 适配器 | 说明 | 适用场景 |
|--------|------|----------|
| `ollama` | 本地运行，无需 API Key | 开发测试、私有部署 |
| `openai` | OpenAI API 或兼容服务 | 云服务、生产环境 |
| `llama_cpp` | llama.cpp 本地推理 | 低资源环境 |
| `transformers` | HuggingFace 模型 | 研究实验 |

#### Ollama（本地运行）

```bash
# 安装并启动 Ollama
ollama pull qwen3

# 配置 ~/.mindbot/settings.json
{
  "providers": {
    "local-ollama": {
      "type": "ollama",
      "endpoints": [{
        "base_url": "http://localhost:11434",
        "models": [{ "id": "qwen3", "role": "chat", "level": "medium" }]
      }]
    }
  },
  "agent": {
    "model": "local-ollama/qwen3"
  }
}
```

#### OpenAI / 兼容服务

```bash
# 设置 API Key
export OPENAI_API_KEY=your-api-key

# 配置 ~/.mindbot/settings.json
{
  "providers": {
    "openai": {
      "type": "openai",
      "endpoints": [{
        "base_url": "https://api.openai.com/v1",
        "api_key": "{env:OPENAI_API_KEY}",
        "models": [{ "id": "gpt-4o", "role": "chat", "level": "high" }]
      }]
    }
  },
  "agent": {
    "model": "openai/gpt-4o"
  }
}
```

**兼容服务**（如 DeepSeek、Moonshot、GLM）只需修改 `base_url`：

```json
{
  "providers": {
    "deepseek": {
      "type": "openai",
      "endpoints": [{
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "{env:DEEPSEEK_API_KEY}",
        "models": [{ "id": "deepseek-chat", "role": "chat", "level": "high" }]
      }]
    }
  },
  "agent": {
    "model": "deepseek/deepseek-chat"
  }
}
```

### 2. 初始化配置

```bash
mindbot generate-config
```

这会创建 `~/.mindbot/settings.json` 和 `~/.mindbot/SYSTEM.md`。

### 3. 开始对话

```python
import asyncio
from mindbot import MindBot

async def main():
    bot = MindBot()
    response = await bot.chat("你好，请介绍一下自己", session_id="user123")
    print(response.content)

asyncio.run(main())
```

---

## CLI 命令

```bash
mindbot <command> [options]

Commands:
  generate-config   初始化配置（别名: onboard）
  serve             启动服务（多通道）
  shell             进入交互式 shell
  chat              发送单条消息
  status            显示状态

  config show       显示当前配置
  config validate   验证配置

Options:
  -c, --config <path>   配置文件路径
  -v, --verbose         详细日志模式
```

### 交互式 Shell

```bash
mindbot shell
```

进入 Shell 后可使用 slash 命令：

| 命令 | 说明 |
|------|------|
| `/model` | 列出所有可用模型 |
| `/model <name>` | 切换到指定模型（如 `/model local-ollama/qwen3`）|
| `/config` | 实时配置命令（授权、设置）|
| `/status` | 显示当前状态 |
| `/help` | 显示帮助 |
| `exit` / `quit` / `bye` | 退出 Shell |

> 使用向上/向下方向键可浏览历史输入，历史存储在 `~/.mindbot/history/`

---

## 多通道支持

### 启动服务

```bash
mindbot serve
```

根据配置中 `enabled: true` 的通道自动启动。

### 飞书机器人

**1. 创建飞书应用**

- 访问 [飞书开放平台](https://open.feishu.cn/app)
- 创建新应用 → 启用 **机器人** 能力
- **权限配置**：添加 `im:message`（发送消息）、`im:message.p2p_msg:readonly`（接收消息）
- **事件订阅**：添加 `im.message.receive_v1`，选择「使用长连接接收事件」
- 获取 **App ID** 和 **App Secret**

**2. 配置**

```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "app_id": "cli_xxx",
      "app_secret": "xxx",
      "encrypt_key": "",
      "verification_token": ""
    }
  }
}
```

> 长连接模式无需公网 IP，飞书通过 WebSocket 推送消息。

**3. 启动**

```bash
mindbot serve
```

### Telegram

```bash
# 从 @BotFather 获取 Token
export TELEGRAM_BOT_TOKEN=your-token

# 配置
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "{env:TELEGRAM_BOT_TOKEN}"
    }
  }
}
```

---

## 文档导航

| 主题 | 链接 |
|------|------|
| 快速开始 | [docs/guide/quickstart.md](docs/guide/quickstart.md) |
| 配置参考 | [docs/configuration/index.md](docs/configuration/index.md) |
| 架构文档 | [docs/architecture/overview.md](docs/architecture/overview.md) |
| 示例代码 | [docs/guide/examples.md](docs/guide/examples.md) |
| CLI 命令 | [docs/guide/cli-reference.md](docs/guide/cli-reference.md) |
| Skills 机制 | [docs/guide/skills.md](docs/guide/skills.md) |
| Benchmark | [docs/testing/toolcall15.md](docs/testing/toolcall15.md) |

---

## 项目结构

```
mindbot/
├── src/mindbot/
│   ├── bot.py            # 对外主入口
│   ├── agent/            # Agent 编排与执行
│   ├── providers/        # LLM 提供商适配
│   ├── routing/          # 模型路由
│   ├── memory/           # 记忆系统
│   ├── capability/       # 能力层
│   ├── channels/         # 多通道支持
│   ├── config/           # 配置管理
│   └── tools/            # 内置工具
├── docs/                 # 文档
├── tests/                # 测试
└── examples/             # 示例代码
```

---

## 架构设计

MindBot 采用 **五层分层架构**，各层之间通过明确的边界规则和单向依赖关系进行解耦。

```
┌─────────────────────────────────────────────────────────────┐
│  L1 接口/传输层                                              │
│  channels/* + bus/* + cli/*                                 │
│  接入外部通道（CLI、HTTP、飞书），通过 MessageBus 解耦        │
├─────────────────────────────────────────────────────────────┤
│  L2 应用/编排层                                              │
│  bot.py + agent/core.py + agent/agent.py + turn_engine.py   │
│  对话主链路编排：组装输入、驱动 TurnEngine 循环、持久化提交   │
├─────────────────────────────────────────────────────────────┤
│  L3 对话领域层                                               │
│  context/manager.py + context/models.py + compression.py    │
│  7 块上下文管理、消息模型、token 预算分配                     │
├─────────────────────────────────────────────────────────────┤
│  L4 能力与记忆层                                             │
│  capability/* + memory/* + generation/* + skills/*          │
│  工具执行、记忆检索、动态工具生成、技能注册与渲染             │
├─────────────────────────────────────────────────────────────┤
│  L5 基础设施适配层                                           │
│  providers/* + routing/* + config/*                         │
│  LLM Provider 适配、模型路由选择、配置加载与热更新            │
└─────────────────────────────────────────────────────────────┘
```

| 层级 | 核心职责 | 关键模块 |
|------|---------|---------|
| L1 | 接入外部通道，消息解耦 | `channels/*`, `bus/*`, `cli/*` |
| L2 | 对话主链路编排 | `bot.py`, `agent/core.py`, `agent/turn_engine.py` |
| L3 | 上下文管理、token 预算 | `context/manager.py`, `context/models.py` |
| L4 | 工具执行、记忆检索 | `capability/*`, `memory/*`, `skills/*` |
| L5 | LLM Provider、模型路由 | `providers/*`, `routing/*`, `config/*` |

### 核心设计原则

- **仅两个聊天接口**：`chat()` 和 `chat_stream()`，所有通道必须通过这两个方法进入主链路
- **全异步架构**：所有 I/O 操作均为 `async`，不阻塞事件循环
- **7 块上下文管理**：system_identity、skills_overview、skills_detail、memory、conversation、intent_state、user_input
- **CapabilityFacade 统一调度**：所有工具执行通过统一入口

---

## 内置工具

| 工具 | 类别 | 说明 |
|------|------|------|
| `read_file` | 文件 | 读取文件内容，支持 offset/limit 分页 |
| `write_file` | 文件 | 创建或覆盖文件，自动创建父目录 |
| `edit_file` | 文件 | 精确文本替换，支持 replace_all |
| `list_directory` | 文件 | 列出目录内容，支持 glob 模式匹配 |
| `file_info` | 文件 | 获取文件/目录基本信息（大小、类型） |
| `exec_command` | Shell | 执行 Shell 命令，带超时和安全检查 |
| `get_mindbot_runtime_info` | 系统 | 获取运行时状态（配置、内存、日志） |
| `fetch_url` | Web | 获取 URL 内容，自动去除 HTML 标签 |

### 路径安全策略

- **workspace**: 默认工作目录，所有相对路径以此解析
- **restrict_to_workspace**: 启用时，文件工具只能在允许根目录内运行
- **system_path_whitelist**: 额外允许的系统路径（如 `~/.mindbot`）
- **shell_execution.policy**: Shell 执行策略（`cwd_guard` 或 `sandboxed`）

---

## License

MIT