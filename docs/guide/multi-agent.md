---
title: 多 Agent 编排
---

# 多 Agent 编排

MindBot 提供了灵活的多 Agent 架构，支持 Supervisor 模式的子 Agent 管理和多 Agent 协作编排。

## 核心概念

### MindAgent（Supervisor）

`MindAgent` 是主 Agent，充当 Supervisor 角色。它负责：

- 管理子 Agent 的注册与生命周期
- 处理用户对话
- 将特定任务分发给子 Agent

`MindAgent` 的代码位于 `agent/core.py`。

### Agent（Worker）

`Agent` 是基础的会话执行单元，充当 Worker 角色。每个 Agent 可以拥有：

- 独立的系统提示词（`system_prompt`）
- 独立的工具集（`tools`）
- 独立的会话上下文

`Agent` 的代码位于 `agent/agent.py`。

### AgentOrchestrator

`AgentOrchestrator` 负责 LLM 调用与 tool loop 的编排，是 Agent 内部执行的核心引擎。代码位于 `agent/orchestrator.py`。

## 多 Agent 协作（MultiAgentOrchestrator）

`MultiAgentOrchestrator` 用于编排多个 Agent 的协作执行，支持顺序模式和并行模式。

### 示例：翻译 / 摘要 / 润色协作

```python
import asyncio
from mindbot.agent.agent import Agent
from mindbot.agent.multi_agent import MultiAgentOrchestrator
from mindbot.builders import create_llm
from mindbot.config.loader import load_config
from pathlib import Path


async def main():
    config = load_config(Path.home() / ".mindbot" / "settings.json")
    llm = create_llm(config)

    # 三个专长不同的 Agent
    translator = Agent(
        name="translator",
        llm=llm,
        system_prompt="你是一名专业翻译，将用户输入的中文翻译成流畅的英文，只输出译文，不加解释。",
    )
    summarizer = Agent(
        name="summarizer",
        llm=llm,
        system_prompt="你是一名文字摘要专家，将用户输入的内容压缩成不超过 30 字的核心摘要。",
    )
    polisher = Agent(
        name="polisher",
        llm=llm,
        system_prompt="你是一名文字润色专家，优化用户输入的句子，使其更加通顺优美，保持原意。",
    )

    orchestrator = MultiAgentOrchestrator()
    orchestrator.set_main_agent(translator)  # 顺序模式用 translator
    orchestrator.register_agent(summarizer)
    orchestrator.register_agent(polisher)

    task = "人工智能技术正在深刻改变人类的生活和工作方式，未来充满无限可能。"

    # 顺序模式（只有主 agent 执行）
    result_seq = await orchestrator.execute(task, session_id="seq", mode="sequential")
    print(result_seq.content)

    # 并行模式（三个 agent 同时执行）
    result_par = await orchestrator.execute(task, session_id="par", mode="parallel")
    print(result_par.content)


asyncio.run(main())
```

运行方式：

```bash
python examples/07_multi_agent.py
```

### 执行模式

| 模式 | 说明 |
|------|------|
| `sequential` | 顺序模式：仅主 Agent（通过 `set_main_agent` 设定）执行任务 |
| `parallel` | 并行模式：所有已注册的 Agent 同时独立处理同一任务，结果合并展示 |

## 子 Agent 管理（Supervisor 模式）

通过 `MindAgent.register_child_agent()` 可以注册子 Agent，每个子 Agent 拥有独立的系统提示词和工具集。

### 示例：天气查询子 Agent

```python
import asyncio
from pathlib import Path
from mindbot.config.loader import load_config
from mindbot.capability.backends.tooling import tool
from mindbot.agent.agent import Agent
from mindbot.agent.core import MindAgent
from mindbot.builders import create_llm


async def main():
    config = load_config(Path.home() / ".mindbot" / "settings.json")
    supervisor = MindAgent(config=config)
    llm = create_llm(config)

    # 定义子 Agent 专用工具
    @tool(description="查询指定城市的当前气温（摄氏度）。")
    def get_temperature(city: str) -> str:
        data = {"北京": "18°C", "上海": "22°C", "广州": "28°C"}
        return data.get(city, f"{city}: 数据不可用")

    # 创建天气子 Agent
    weather_agent = Agent(
        name="weather_agent",
        llm=llm,
        tools=[get_temperature],
        system_prompt="你是天气查询专员，只回答天气相关问题，数据来自内置工具。",
    )

    # 注册到 MindAgent supervisor
    supervisor.register_child_agent(weather_agent)

    # 查看已注册的子 Agent
    print("已注册子 Agent:", [a.name for a in supervisor.list_child_agents()])

    # 主 Agent 正常对话
    r1 = await supervisor.chat("你好，你能做什么？")
    print(f"[主Agent] {r1.content}")

    # 子 Agent 独立对话（有自己的 session 和工具）
    r2 = await weather_agent.chat("北京和上海哪个更热？")
    print(f"[子Agent weather_agent] {r2.content}")


asyncio.run(main())
```

运行方式：

```bash
python examples/10_child_agent.py
```

### 关键 API

| API | 说明 |
|-----|------|
| `MindAgent(config)` | 创建 Supervisor 实例 |
| `supervisor.register_child_agent(agent)` | 注册子 Agent |
| `supervisor.list_child_agents()` | 列出所有已注册的子 Agent |
| `supervisor.chat(message)` | 主 Agent 对话 |
| `child_agent.chat(message)` | 子 Agent 独立对话 |

## 架构总结

```
MindAgent (Supervisor)
├── 主对话: supervisor.chat()
├── 子 Agent: weather_agent (独立 tools + prompt)
├── 子 Agent: translator_agent (独立 tools + prompt)
└── ...
```

每个 Agent（无论是 MindAgent 还是子 Agent）都通过独立的 TurnEngine 运行（InputBuilder -> TurnEngine -> PersistenceWriter），互不干扰。

## 下一步

- [示例代码](examples.md) -- 运行示例 07 和示例 10 体验多 Agent 功能
- [Skills 机制](skills.md) -- 为 Agent 注入专业知识技能
