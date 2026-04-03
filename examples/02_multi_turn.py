#!/usr/bin/env python3
"""Example 02: 多轮对话（会话保持）。

演示：
- 使用同一个 session_id 进行多轮对话
- Bot 能够记住上下文（"你叫什么名字" → "我叫 Alice" → "你再说一遍你叫什么"）
- 不同 session_id 的对话相互隔离

Run::

    python -m examples.02_multi_turn
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from mindbot.config.loader import load_config


async def main() -> None:
    from mindbot import MindBot

    bot = MindBot(config=load_config(Path.home() / ".mindbot" / "settings.json"))

    # 同一 session 的多轮对话
    session_id = "demo-session-alice"
    conversation = [
        "我叫 Alice，你好！",
        "我刚才告诉你我叫什么名字了吗？",
        "那你帮我总结一下我们刚才聊了什么。",
    ]

    print("=== 会话 A（记忆上下文）===")
    for turn, message in enumerate(conversation, 1):
        print(f"\n[Turn {turn}] User: {message}")
        response = await bot.chat(message, session_id=session_id)
        print(f"[Turn {turn}] Assistant: {response.content}")

    # 另一个 session 无法访问上面的上下文
    print("\n\n=== 会话 B（全新 session，上下文隔离）===")
    response = await bot.chat("我叫什么名字？", session_id="demo-session-bob")
    print(f"Assistant: {response.content}")


if __name__ == "__main__":
    asyncio.run(main())
