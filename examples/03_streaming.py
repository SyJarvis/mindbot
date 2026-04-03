#!/usr/bin/env python3
"""Example 03: 流式输出（Streaming）。

演示：
- 使用 bot.chat_stream() 逐 token 输出
- 在终端实时打印，无等待感
- 统计总字符数和用时

Run::

    python -m examples.03_streaming
    python -m examples.03_streaming --message "用 300 字介绍一下量子计算"
"""

from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path

async def main() -> None:
    parser = argparse.ArgumentParser(description="MindBot 流式输出示例")
    parser.add_argument("--config", type=Path, default=Path.home() / ".mindbot" / "settings.yaml")
    parser.add_argument("--message", type=str, default="请用 200 字介绍一下人工智能的发展历史。")
    args = parser.parse_args()

    from mindbot import MindBot
    from mindbot.config.loader import load_config
    bot = MindBot(config=load_config(Path.home() / ".mindbot" / "settings.json"))

    print(f"User: {args.message}")
    print("-" * 60)
    print("Assistant: ", end="", flush=True)

    start = time.perf_counter()
    total_chars = 0

    async for chunk in bot.chat_stream(args.message):
        print(chunk, end="", flush=True)
        total_chars += len(chunk)

    elapsed = time.perf_counter() - start
    print(f"\n\n[Stats] {total_chars} chars in {elapsed:.2f}s ({total_chars / elapsed:.0f} chars/s)")


if __name__ == "__main__":
    asyncio.run(main())
