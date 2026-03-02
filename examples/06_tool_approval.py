#!/usr/bin/env python3
"""Example 06: 人工审批（Human-in-the-loop Tool Approval）。

演示：
- 配置需要审批的工具
- 在 on_event 回调中捕获 TOOL_CALL_REQUEST 事件
- 用户在终端输入 allow / deny 来决定是否执行工具

Run::

    python -m examples.06_tool_approval
"""

from __future__ import annotations

import asyncio

from mindbot.agent.models import AgentEvent, ApprovalDecision, EventType


def make_config():
    from mindbot.config.schema import AgentConfig, Config, ProviderConfig, ToolApprovalConfig, ToolAskMode

    approval = ToolApprovalConfig(
        ask=ToolAskMode.ALWAYS,  # 每次都要求审批
        whitelist={},
        timeout=60,
    )
    return Config(
        agent=AgentConfig(model="ollama/qwen3-vl:8b", max_tool_iterations=5, approval=approval),
        providers={"ollama": ProviderConfig(base_url="http://localhost:11434", api_key="")},
    )


async def main() -> None:
    from mindbot.capability.backends.tooling import tool
    from mindbot import MindBot

    @tool(description="删除指定文件（危险操作，需要用户确认）。")
    def delete_file(path: str) -> str:
        """Simulate deleting a file. In production this would be os.remove(path)."""
        return f"[模拟] 文件 {path!r} 已删除。"

    @tool(description="列出目录内容（安全操作）。")
    def list_dir(directory: str = ".") -> str:
        """List files in a directory."""
        import os
        try:
            entries = os.listdir(directory)
            return "\n".join(entries[:20])
        except Exception as exc:
            return f"Error: {exc}"

    bot = MindBot(config=make_config())
    pending_approvals: dict[str, str] = {}  # request_id → tool_name

    def on_event(event: AgentEvent) -> None:
        if event.type == EventType.TOOL_CALL_REQUEST:
            rid = event.data["request_id"]
            tool_name = event.data["tool_name"]
            args = event.data["arguments"]
            pending_approvals[rid] = tool_name
            print(f"\n⚠️  工具调用请求: {tool_name}({args})")
        elif event.type == EventType.TOOL_EXECUTING:
            print(f"  ▶ 执行工具: {event.data['tool_name']}")
        elif event.type == EventType.TOOL_RESULT:
            print(f"  ✅ 工具结果: {event.data.get('result', '')!r}")

    message = "先列出当前目录，然后删除 /tmp/test.txt。"
    print(f"User: {message}")
    print("-" * 60)
    print("(提示：遇到审批请求时，输入 allow 或 deny)\n")

    # 在后台跑 chat，并在前台等待审批输入
    async def run_chat():
        return await bot.chat(message, tools=[delete_file, list_dir], on_event=on_event)

    chat_task = asyncio.create_task(run_chat())

    # 给 bot 一点时间启动并发出审批请求
    while not chat_task.done():
        await asyncio.sleep(0.1)
        if pending_approvals:
            rid, tool_name = next(iter(pending_approvals.items()))
            decision_str = input(f"  → 是否允许执行 {tool_name}? [allow/deny]: ").strip().lower()
            decision = ApprovalDecision.ALLOW_ONCE if decision_str == "allow" else ApprovalDecision.DENY
            bot._agent.resolve_approval(rid, decision.value)
            del pending_approvals[rid]

    response = await chat_task
    print("-" * 60)
    print(f"Assistant: {response.content}")


if __name__ == "__main__":
    asyncio.run(main())
