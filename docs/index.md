# MindBot

基于 **Python + asyncio** 的模块化 AI Agent 框架，支持多 Provider、动态路由、流式响应和工具确认机制。

[![Version](https://img.shields.io/badge/Version-0.3.1-blue.svg)](https://github.com/SyJarvis/mindbot)
[![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## 快速链接

| | |
|---|---|
| [:rocket: 快速开始](guide/quickstart.md) | 5 分钟上手，配置 LLM、初始化、开始对话 |
| [:material-brain: 架构概览](architecture/overview.md) | 五层架构与执行流程详解 |
| [:material-cog: 配置参考](configuration/index.md) | Provider、路由、安全、通道配置 |
| [:material-code-braces: 示例代码](guide/examples.md) | 11 个从简到难的示例讲解 |

---

## 特性一览

| | |
|---|---|
| **统一入口** | `AgentOrchestrator` 自主决策，无需预选模式 |
| **流式响应** | 实时事件流，用户可看到 Agent 思考过程 |
| **工具确认** | 多级安全确认机制（安全级别、白名单、危险工具检测）|
| **路径安全** | 工作空间隔离 + 系统路径白名单，防止越权访问 |
| **智能路由** | 根据内容类型/复杂度/关键词自动选择模型 |
| **多 Provider** | OpenAI / Ollama / Transformers / llama.cpp |
| **记忆系统** | 短期/长期记忆，向量检索，自动归档 |
| **Skills 机制** | `SKILL.md` 技能包按需注入 prompt |
| **上下文管理** | Token 预算管理，自动压缩，工具持久化策略 |
| **多通道支持** | CLI、HTTP、飞书、Telegram |

---

## 30 秒上手

```python
import asyncio
from mindbot import MindBot

async def main():
    bot = MindBot()
    response = await bot.chat("你好，请介绍一下自己", session_id="user123")
    print(response.content)

asyncio.run(main())
```

??? note "更多用法"

    === "流式输出"

        ```python
        async for chunk in bot.chat_stream("讲个故事"):
            print(chunk, end="", flush=True)
        ```

    === "事件回调"

        ```python
        response = await bot.chat(
            "帮我计算 25 * 37",
            session_id="user123",
            on_event=lambda e: print(f"[{e.type}] {e.data}"),
        )
        ```

    === "CLI 使用"

        ```bash
        # 交互式 shell
        mindbot shell

        # 单条消息
        mindbot chat "你好"

        # 启动多通道服务
        mindbot serve
        ```
