#!/usr/bin/env python3
"""Example 04: 使用 on_event 回调监听执行过程。

演示：
- 通过 on_event 实时接收 AgentEvent（思考中、工具调用、结果等）
- 可用于日志采集、进度展示、可观测性接入

Run::

    python -m examples.04_event_callbacks
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from mindbot.agent.models import AgentEvent, EventType
from mindbot.config.loader import load_config

def on_event(event: AgentEvent) -> None:
    """Print a summary line for each agent event."""
    match event.type:
        case EventType.THINKING:
            print(f"  [thinking] turn={event.data.get('turn', 0)}")
        case EventType.DELTA:
            # Streaming content chunk — show a preview
            preview = event.data.get("content", "")[:40]
            print(f"  [delta] {preview!r}")
        case EventType.TOOL_EXECUTING:
            print(f"  [tool_executing] {event.data['tool_name']}")
        case EventType.TOOL_RESULT:
            result_preview = str(event.data.get("result", ""))[:80]
            print(f"  [tool_result] {event.data['tool_name']} -> {result_preview!r}")
        case EventType.COMPLETE:
            print(f"  [complete] stop_reason={event.data['stop_reason']}")
        case EventType.ERROR:
            print(f"  [error] {event.data['message']}")
        case _:
            print(f"  [event] {event.type.value}")


async def main() -> None:
    from mindbot.capability.backends.tooling import tool

    @tool()
    def get_time() -> str:
        """Return the current UTC time as an ISO-8601 string."""
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()

    from mindbot import MindBot

    bot = MindBot(config=load_config(Path.home() / ".mindbot" / "settings.json"))

    message = "现在几点了？请用工具查询一下当前时间。"
    print(f"User: {message}")
    print("-" * 60)

    response = await bot.chat(message, tools=[get_time], on_event=on_event)

    print("-" * 60)
    print(f"Assistant: {response.content}")


if __name__ == "__main__":
    asyncio.run(main())
