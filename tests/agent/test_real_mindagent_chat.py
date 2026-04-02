"""Integration test: real MindAgent 对话，打印 AI 返回内容。

运行方式（需加 -s 才能看到打印）:
  PYTHONPATH=src pytest --noconftest tests/agent/test_real_mindagent_chat.py -s -v

若 ~/.mindbot/settings.yaml 不存在则跳过。
默认关闭工具审批，避免测试卡在 request_approval 上。
"""

from __future__ import annotations

from pathlib import Path

import pytest

# 与飞书用户问题一致
USER_MESSAGE = "查看~/research目录下有啥文件..."


@pytest.mark.asyncio
async def test_real_mindagent_chat_list_research_dir() -> None:
    """用真实 MindAgent 发送「查看~/research目录下有啥文件」，打印 AI 回复。"""
    config_file = Path.home() / ".mindbot" / "settings.yaml"
    if not config_file.exists():
        pytest.skip(f"Config not found: {config_file} (run mindbot generate-config)")

    from mindbot.bot import MindBot
    from mindbot.config.loader import load_config
    from mindbot.config.schema import ToolAskMode

    config = load_config(config_file)
    config.agent.approval.ask = ToolAskMode.OFF  # 测试中不等待审批，避免卡住
    bot = MindBot(config=config)
    response = await bot.chat(USER_MESSAGE, session_id="test_list_research")

    print("\n" + "=" * 60)
    print("用户:", USER_MESSAGE)
    print("=" * 60)
    print("AI 返回内容:")
    print(response.content or "(空)")
    print("=" * 60 + "\n")

    assert response.content is not None
    assert len(response.content.strip()) > 0
