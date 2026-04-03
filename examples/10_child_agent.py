#!/usr/bin/env python3
"""Example 10: MindAgent 子 Agent 管理（Supervisor 模式）。

演示：
- 通过 MindAgent.register_child_agent() 注册子 Agent
- 子 Agent 拥有独立的系统提示词和工具集
- 每个 Agent 通过 TurnEngine 独立运行（InputBuilder → TurnEngine → PersistenceWriter）

Run::

    python -m examples.10_child_agent
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from mindbot.config.loader import load_config


def make_config():
    """Load the user's existing provider config from settings.json."""
    return load_config(Path.home() / ".mindbot" / "settings.json")


async def main() -> None:
    from mindbot.capability.backends.tooling import tool
    from mindbot.agent.agent import Agent
    from mindbot.agent.core import MindAgent
    from mindbot.builders import create_llm

    config = make_config()
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

    print("已注册子 Agent:", [a.name for a in supervisor.list_child_agents()])
    print("-" * 60)

    # 主 Agent 正常对话
    r1 = await supervisor.chat("你好，你能做什么？")
    print(f"[主Agent] {r1.content}\n")

    # 子 Agent 独立对话（有自己的 session 和工具）
    r2 = await weather_agent.chat("北京和上海哪个更热？")
    print(f"[子Agent weather_agent] {r2.content}")


if __name__ == "__main__":
    asyncio.run(main())
