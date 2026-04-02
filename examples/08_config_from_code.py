#!/usr/bin/env python3
"""Example 08: 纯代码构建配置（不依赖 settings.yaml）。

演示：
- 用 Pydantic 模型直接在代码中构造 Config，适合嵌入式 / 测试场景
- 展示常用配置项：model、system_prompt、max_tool_iterations、context window

Run::

    python -m examples.08_config_from_code
"""

from __future__ import annotations

import asyncio


async def main() -> None:
    from mindbot.config.schema import (
        AgentConfig,
        Config,
        ContextConfig,
        ProviderConfig,
    )
    from mindbot import MindBot

    config = Config(
        agent=AgentConfig(
            model="ollama/qwen3-vl:8b",
            system_prompt="你是一个简洁的助手，回答不超过 50 字。",
            max_tool_iterations=3,
        ),
        # context is a root-level field on Config, not inside AgentConfig
        context=ContextConfig(
            max_tokens=4096,  # 上下文窗口 token 上限
        ),
        providers={
            "ollama": ProviderConfig(
                base_url="http://localhost:11434",
                api_key="",
            )
        },
    )

    print("Config summary:")
    print(f"  model             = {config.agent.model}")
    print(f"  system_prompt     = {config.agent.system_prompt!r}")
    print(f"  max_tool_iter     = {config.agent.max_tool_iterations}")
    print(f"  max_tokens        = {config.context.max_tokens}")
    print(f"  max_sessions      = {config.agent.max_sessions}")
    print("-" * 60)

    bot = MindBot(config=config)
    response = await bot.chat("你好，请介绍一下你自己。")
    print(f"Assistant: {response.content}")


if __name__ == "__main__":
    asyncio.run(main())
