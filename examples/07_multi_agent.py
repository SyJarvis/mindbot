#!/usr/bin/env python3
"""Example 07: 多 Agent 协作（顺序 & 并行）。

演示：
- 构建三个专长不同的 Agent（翻译、摘要、润色）
- 顺序模式：主 Agent 完成整条任务
- 并行模式：三个 Agent 同时独立处理同一问题，结果合并展示

Run::

    python -m examples.07_multi_agent
"""

from __future__ import annotations

import asyncio


def make_config():
    from mindbot.config.schema import AgentConfig, Config, ProviderConfig

    return Config(
        agent=AgentConfig(model="ollama/qwen3-vl:8b"),
        providers={"ollama": ProviderConfig(base_url="http://localhost:11434", api_key="")},
    )


def make_llm(config=None):
    from mindbot.builders import create_llm

    return create_llm(config or make_config())


async def main() -> None:
    from mindbot.agent.agent import Agent
    from mindbot.agent.multi_agent import MultiAgentOrchestrator

    config = make_config()
    llm = make_llm(config)

    # 三个专长不同的 Agent
    translator = Agent(
        name="translator",
        llm=llm,
        system_prompt="你是一名专业翻译，将用户输入的中文翻译成流畅的英文，只输出译文，不加解释。",
    )
    summarizer = Agent(
        name="summarizer",
        llm=llm,
        system_prompt="你是一名文字摘要专家，将用户输入的内容压缩成不超过 30 字的核心摘要。",
    )
    polisher = Agent(
        name="polisher",
        llm=llm,
        system_prompt="你是一名文字润色专家，优化用户输入的句子，使其更加通顺优美，保持原意。",
    )

    orchestrator = MultiAgentOrchestrator()
    orchestrator.set_main_agent(translator)  # 顺序模式用 translator
    orchestrator.register_agent(summarizer)
    orchestrator.register_agent(polisher)

    task = "人工智能技术正在深刻改变人类的生活和工作方式，未来充满无限可能。"

    print(f"Task: {task}\n")

    # 顺序模式（只有主 agent 执行）
    print("=== 顺序模式（主 Agent: translator）===")
    result_seq = await orchestrator.execute(task, session_id="seq", mode="sequential")
    print(result_seq.content)

    # 并行模式（三个 agent 同时执行）
    print("\n=== 并行模式（三个 Agent 同时执行）===")
    result_par = await orchestrator.execute(task, session_id="par", mode="parallel")
    print(result_par.content)


if __name__ == "__main__":
    asyncio.run(main())
