#!/usr/bin/env python3
"""Example 05: 自定义系统提示词（角色扮演）。

演示：
- 通过 AgentConfig.system_prompt 让 bot 扮演特定角色
- 对比同一问题在不同角色下的回答风格

Run::

    python -m examples.05_system_prompt
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from mindbot.config.loader import load_config


def make_config(system_prompt: str):
    """Load the user's config file and override only the system prompt."""
    config = load_config(Path.home() / ".mindbot" / "settings.json")
    config.agent.system_prompt = system_prompt
    return config

async def chat_as(role_name: str, system_prompt: str, message: str) -> None:
    from mindbot.agent.core import MindAgent

    agent = MindAgent(config=make_config(system_prompt))
    response = await agent.chat(message)
    print(f"\n[{role_name}]\n{response.content}\n")


async def main() -> None:
    question = "为什么天空是蓝色的？"
    print(f"问题：{question}")
    print("=" * 60)

    await chat_as(
        role_name="幼儿园老师",
        system_prompt="你是一位耐心的幼儿园老师，用非常简单、有趣的语言向小朋友解释事物，不超过 50 字。",
        message=question,
    )

    await chat_as(
        role_name="物理学教授",
        system_prompt="你是一位严谨的物理学教授，用精确的科学术语解释现象，引用瑞利散射理论。",
        message=question,
    )

    await chat_as(
        role_name="诗人",
        system_prompt="你是一位浪漫的诗人，用诗意的语言描述自然现象，尽量以诗的形式回答。",
        message=question,
    )


if __name__ == "__main__":
    asyncio.run(main())
