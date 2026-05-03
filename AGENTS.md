# AGENTS.md — MindBot AI Agent 指令

## 项目入口

| 入口 | 路径 | 说明 |
|------|------|------|
| 核心 | `src/mindbot/bot.py` | `MindBot` 类，`chat()` / `chat_stream()` |
| CLI | `mindbot` 命令 | `src/mindbot/cli/__init__.py:app` |
| 配置 | `~/.mindbot/settings.json` | 支持 `$MIND_CONFIG_PATH` 覆盖 |

```bash
uv sync                    # 安装依赖
uv sync --extra dev        # + pytest, ruff
pytest tests/              # 测试
ruff check src/ tests/     # Lint
mindbot shell              # 交互式 shell
mindbot serve              # 多通道服务
```

## 架构决策规则

### 五层架构与依赖方向

```
L1 通道层 (channels/) ──→ L2 编排层 (bot.py, agent/)
                         ↓
         L3 上下文层 (context/) ←── L4 能力层 (capability/, skills/)
                         ↓
         L5 基础设施层 (providers/, routing/, config/)
```

**允许的依赖方向：只能向下依赖。**
- L1 → L2 → L3/L4/L5，L3 → L5（仅压缩策略），L4 → L5
- **禁止**：L3 → L2（上下文不能调用编排），L1 → L4（通道不能直接执行工具）

### 新功能落在哪一层？

| 你要做的 | 落在哪层 | 判断依据 |
|---------|---------|---------|
| 接入新平台（Discord、微信） | L1 通道层 | 对接外部消息协议 |
| 修改对话流程、多 Agent 协作 | L2 编排层 | 控制对话流转逻辑 |
| 改上下文管理、压缩策略 | L3 上下文层 | 纯状态管理 |
| 加新工具、新技能 | L4 能力层 | 可执行的能力 |
| 接入新 LLM、改路由策略 | L5 基础设施层 | 外部服务适配 |

### 铁律

1. **只有两个入口**：`chat()` 和 `chat_stream()`，所有通道必须通过它们进入主链路
2. **工具执行**：所有工具通过 `CapabilityFacade.resolve_and_execute()` 统一调度
3. **全异步**：所有 I/O 必须是 `async`，禁止阻塞事件循环。同步操作用 `run_sync()` 包装
4. **工具定义与实现分离**：Tool 定义在 `tools/`，handler 在 `capability/backends/`
5. **TurnEngine 是唯一执行循环**：LLM ↔ Tool 的迭代循环只在 TurnEngine 内
6. **配置热更新**：通过 ConfigBus 事件总线实时生效，不要缓存配置后忘记更新

### Skill 机制 vs 硬编码

- **用 Skill**：提示层面的知识注入、可插拔的行为指导、用户可自定义的领域知识
- **硬编码**：核心架构逻辑、不可变的铁律、性能关键的路径

## 开发约束

### 目录职责

| 目录 | 职责 |
|------|------|
| `agent/` | Agent 编排（MindAgent, Agent, TurnEngine, InputBuilder） |
| `providers/` | LLM 适配器（OpenAI, Ollama, Hailo, Transformers） |
| `routing/` | 模型路由选择与 fallback |
| `memory/` | 记忆系统（短期 + 长期） |
| `capability/` | 工具统一调度（Facade → Executor → Backend） |
| `channels/` | 通道（CLI, HTTP, 飞书, Telegram） |
| `skills/` | 技能加载、选择、渲染 |
| `config/` | 配置加载与热更新 |
| `context/` | 7-block 上下文窗口与压缩 |

### 测试约定

- `asyncio_mode = "auto"`：异步测试无需显式装饰器
- 测试目录与 src 对应：`tests/agent/` → `src/mindbot/agent/`
- 用 `FakeLLM` 做 Provider 替身，用 `AsyncMock` mock 异步方法
- benchmark 测试已排除：`collect_ignore_glob = ["tests/benchmarking/*"]`

### 参考文档

- 完整架构：`docs/architecture/overview.md`
- 配置指南：`docs/configuration/guide-zh.md`
- 技能机制：`docs/guide/skills.md`
