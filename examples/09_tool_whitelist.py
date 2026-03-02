#!/usr/bin/env python3
"""Example 09: 工具白名单——预先授权、运行时动态更新。

演示：
- 通过 ToolApprovalConfig 预先白名单特定工具（无需每次审批）
- 运行时通过 agent.add_tool_to_whitelist() 动态追加
- 对比白名单内外工具的行为差异

Run::

    python -m examples.09_tool_whitelist
"""

from __future__ import annotations

import asyncio


def make_config(whitelist: dict):
    from mindbot.config.schema import AgentConfig, Config, ProviderConfig, ToolApprovalConfig, ToolAskMode

    approval = ToolApprovalConfig(
        ask=ToolAskMode.ON_MISS,  # 不在白名单时才询问
        whitelist=whitelist,
        timeout=10,
    )
    return Config(
        agent=AgentConfig(model="ollama/qwen3-vl:8b", max_tool_iterations=5, approval=approval),
        providers={"ollama": ProviderConfig(base_url="http://localhost:11434", api_key="")},
    )


async def main() -> None:
    from mindbot.capability.backends.tooling import tool
    from mindbot import MindBot

    @tool(description="安全：获取当前时间（已预置白名单）。")
    def get_time() -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    @tool(description="安全：将两数相加（运行时加入白名单）。")
    def add(a: int, b: int) -> str:
        return str(a + b)

    # get_time 预置白名单，add 不在白名单中
    bot = MindBot(config=make_config(whitelist={"get_time": [".*"]}))

    print("=== 场景 1：get_time 在白名单，自动执行 ===")
    r1 = await bot.chat("现在是几点？", tools=[get_time])
    print(f"Assistant: {r1.content}\n")

    # 动态把 add 加入白名单，然后再次调用
    bot._agent.add_tool_to_whitelist("add", pattern=".*")
    print("=== 场景 2：动态加入白名单后，add 也自动执行 ===")
    r2 = await bot.chat("请帮我计算 123 加 456。", tools=[get_time, add])
    print(f"Assistant: {r2.content}")


if __name__ == "__main__":
    asyncio.run(main())
