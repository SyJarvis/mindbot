#!/usr/bin/env python3
"""Example 09: tool_persistence 配置——控制工具消息如何保存到会话历史。

演示：
- ``tool_persistence="none"``  — 工具调用/结果不写入对话历史
- ``tool_persistence="summary"`` — 折叠为一条摘要消息
- ``tool_persistence="full"``   — 完整保留所有工具消息

.. note::

    自统一主链重构后，PersistenceWriter 统一管理 conversation、
    memory、journal 的写入。tool_persistence 决定工具调用消息
    在对话上下文中的保留策略。

Run::

    python -m examples.09_tool_whitelist
"""

from __future__ import annotations

import asyncio


def make_config(tool_persistence: str = "summary"):
    from mindbot.config.schema import AgentConfig, Config, ProviderConfig

    return Config(
        agent=AgentConfig(
            model="ollama/qwen3-vl:8b",
            max_tool_iterations=5,
            tool_persistence=tool_persistence,
        ),
        providers={"ollama": ProviderConfig(base_url="http://localhost:11434", api_key="")},
    )


async def demo_persistence(mode: str) -> None:
    from mindbot.capability.backends.tooling import tool
    from mindbot import MindBot

    @tool(description="将两数相加。")
    def add(a: int, b: int) -> str:
        return str(a + b)

    bot = MindBot(config=make_config(tool_persistence=mode))

    r = await bot.chat("请帮我计算 100 + 200。", tools=[add])
    print(f"  Assistant: {r.content}")

    # Second turn — check how much context the bot sees
    r2 = await bot.chat("刚才计算的结果是什么？")
    print(f"  Follow-up: {r2.content}")


async def main() -> None:
    for mode in ("none", "summary", "full"):
        print(f"\n=== tool_persistence={mode!r} ===")
        await demo_persistence(mode)

    print("\n" + "-" * 60)
    print("Tip: 'none' drops tool messages (saves context tokens);")
    print("     'summary' keeps a compact note; 'full' retains everything.")


if __name__ == "__main__":
    asyncio.run(main())
