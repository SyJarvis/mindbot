#!/usr/bin/env python3
"""Example 06: 工具直接执行与事件监听。

演示：
- 注册多个工具，让 LLM 自行决定调用哪个
- 通过 on_event 回调观察 TurnEngine 的执行流程
- 展示 AgentResponse.message_trace 中的完整调用记录

.. note::

    自统一主链重构后，工具调用由 TurnEngine 直接执行，
    不再需要人工审批流程。

Run::

    python -m examples.06_tool_approval
"""

from __future__ import annotations

import asyncio

from mindbot.agent.models import AgentEvent, EventType


def make_config():
    from mindbot.config.schema import AgentConfig, Config, ProviderConfig

    return Config(
        agent=AgentConfig(model="ollama/qwen3-vl:8b", max_tool_iterations=5),
        providers={"ollama": ProviderConfig(base_url="http://localhost:11434", api_key="")},
    )


async def main() -> None:
    from mindbot.capability.backends.tooling import tool
    from mindbot import MindBot

    @tool(description="列出目录内容（安全操作）。")
    def list_dir(directory: str = ".") -> str:
        """List files in a directory."""
        import os
        try:
            entries = os.listdir(directory)
            return "\n".join(entries[:20])
        except Exception as exc:
            return f"Error: {exc}"

    @tool(description="获取当前 UTC 时间。")
    def get_time() -> str:
        """Return the current UTC time as an ISO-8601 string."""
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()

    events_log: list[str] = []

    def on_event(event: AgentEvent) -> None:
        match event.type:
            case EventType.THINKING:
                events_log.append(f"thinking (turn={event.data.get('turn', 0)})")
            case EventType.TOOL_EXECUTING:
                events_log.append(f"executing -> {event.data['tool_name']}")
            case EventType.TOOL_RESULT:
                preview = str(event.data.get("result", ""))[:60]
                events_log.append(f"result <- {event.data['tool_name']}: {preview}")
            case EventType.COMPLETE:
                events_log.append(f"complete ({event.data['stop_reason']})")
            case _:
                events_log.append(f"{event.type.value}")

    bot = MindBot(config=make_config())
    message = "先列出当前目录，然后告诉我现在几点了。"

    print(f"User: {message}")
    print("-" * 60)

    response = await bot.chat(message, tools=[list_dir, get_time], on_event=on_event)

    print(f"Assistant: {response.content}")
    print("-" * 60)

    print("\nEvent log:")
    for entry in events_log:
        print(f"  {entry}")

    print(f"\nMessage trace ({len(response.message_trace)} messages):")
    for msg in response.message_trace:
        role = msg.role
        preview = str(msg.content)[:60] if msg.content else "(tool_calls)"
        print(f"  [{role}] {preview}")


if __name__ == "__main__":
    asyncio.run(main())
