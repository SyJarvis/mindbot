#!/usr/bin/env python3
"""Example 01: 最简单的单轮对话。

演示：
- 从配置文件初始化 MindBot
- 发送一条消息，打印回复
- 打印 stop_reason

Run::

    python -m examples.01_simple_chat
    python -m examples.01_simple_chat --message "给我讲个笑话"
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path


def make_config(config_path: Path | None):
    from mindbot.config.loader import load_config
    from mindbot.config.schema import AgentConfig, Config, ProviderConfig

    if config_path and config_path.exists():
        return load_config(config_path)
    return Config(
        agent=AgentConfig(model="ollama/qwen3-vl:8b"),
        providers={"ollama": ProviderConfig(base_url="http://localhost:11434", api_key="")},
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description="MindBot 最简单对话示例")
    parser.add_argument("--config", type=Path, default=Path.home() / ".mindbot" / "settings.yaml")
    parser.add_argument("--message", type=str, default="你好，请用一句话介绍一下你自己。")
    args = parser.parse_args()

    from mindbot import MindBot

    bot = MindBot(config=make_config(args.config))

    print(f"User: {args.message}")
    print("-" * 60)

    response = await bot.chat(args.message)

    print(f"Assistant: {response.content}")
    print(f"Stop reason: {response.stop_reason}")


if __name__ == "__main__":
    asyncio.run(main())
