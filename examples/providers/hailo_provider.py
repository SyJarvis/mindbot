#!/usr/bin/env python3
"""Hailo provider example — 直接使用 Hailo NPU 进行推理。

演示三种使用方式：
1. 通过 ProviderFactory 直接创建
2. 通过 ProviderAdapter 包装使用
3. 通过 MindBot 配置文件集成

前置条件：
- Hailo 硬件已连接（Hailo-10H / Hailo-8L）
- hailo_platform 已安装（pip install hailort）
- HEF 模型文件已下载到 ~/.local/share/hailo-ollama/models/blob/

Run::

    # 方式 1: 直接使用 provider
    python -m examples.providers.hailo_provider --mode factory

    # 方式 2: 通过 adapter
    python -m examples.providers.hailo_provider --mode adapter

    # 方式 3: 完整 MindBot 配置
    python -m examples.providers.hailo_provider --mode full
"""

from __future__ import annotations

import asyncio
import argparse

from mindbot.context.models import Message


async def demo_factory():
    """方式 1: 通过 ProviderFactory 直接创建 Hailo provider。"""
    from mindbot.providers.factory import ProviderFactory
    # 确保已注册
    import mindbot.providers  # noqa: F401
    # 用字典配置创建
    provider = ProviderFactory.create("hailo", {
        "model": "qwen3:1.7b",
        "max_tokens": 256,
    })
    print("=" * 60)
    print("方式 1: ProviderFactory 直接创建")
    print(f"Provider info: {provider.get_info()}")
    print(f"Available models: {provider.get_model_list()}")
    print("-" * 60)
    messages = [Message(role="user", content="你好，用一句话介绍你自己。")]
    response = await provider.chat(messages)
    print(f"User: 你好，用一句话介绍你自己。")
    print(f"Assistant: {response.content}")
    print(f"Finish reason: {response.finish_reason}")
    # await provider.aclose()


async def demo_adapter():
    """方式 2: 通过 ProviderAdapter 包装使用。"""
    from mindbot.providers.adapter import ProviderAdapter

    # 确保已注册
    import mindbot.providers  # noqa: F401

    adapter = ProviderAdapter("hailo", {"model": "qwen3:1.7b", "max_tokens": 256})

    print("=" * 60)
    print("方式 2: ProviderAdapter")
    print(f"Info: {adapter.get_info()}")
    print("-" * 60)

    messages = [Message(role="user", content="1+1等于几？只回答数字。")]

    # 非流式
    response = await adapter.chat(messages)
    print(f"User: 1+1等于几？只回答数字。")
    print(f"Assistant: {response.content}")

    # 流式
    print("\n--- 流式输出 ---")
    messages2 = [Message(role="user", content="从1数到5")]
    print("User: 从1数到5")
    print("Assistant: ", end="", flush=True)
    async for chunk in adapter.chat_stream(messages2):
        print(chunk, end="", flush=True)
    print()

    await adapter._provider.aclose()


async def demo_full():
    """方式 3: 通过完整 MindBot 配置使用 Hailo provider。

    对应的 settings.json 配置::

        {
          "providers": {
            "local-hailo": {
              "type": "hailo",
              "endpoints": [
                {
                  "base_url": "local",
                  "models": [
                    {
                      "id": "qwen3:1.7b",
                      "role": "chat",
                      "level": "low",
                      "vision": false
                    }
                  ]
                }
              ]
            }
          },
          "agent": {
            "model": "local-hailo/qwen3:1.7b"
          }
        }
    """
    from mindbot.config.schema import AgentConfig, Config, ContextConfig, ProviderInstanceConfig, EndpointConfig, ModelConfig
    from mindbot.agent.core import MindAgent

    config = Config(
        agent=AgentConfig(
            model="local-hailo/qwen3:1.7b",
            system_prompt="你是一个简洁的助手。",
            max_tool_iterations=3,
        ),
        context=ContextConfig(max_tokens=4096),
        providers={
            "local-hailo": ProviderInstanceConfig(
                type="hailo",
                endpoints=[
                    EndpointConfig(
                        base_url="local",
                        models=[
                            ModelConfig(id="qwen3:1.7b", role="chat", level="low", vision=False),
                        ],
                    )
                ],
            )
        },
    )

    print("=" * 60)
    print("方式 3: MindBot 完整配置")
    print(f"  model: {config.agent.model}")
    print("-" * 60)

    agent = MindAgent(config=config)
    response = await agent.chat("介绍一下什么是大语言模型，用一句话回答。")
    print(f"User: 介绍一下什么是大语言模型，用一句话回答。")
    print(f"Assistant: {response.content}")


MODES = {
    "factory": demo_factory,
    "adapter": demo_adapter,
    "full": demo_full,
}


async def main():
    parser = argparse.ArgumentParser(description="Hailo provider example")
    parser.add_argument(
        "--mode", choices=list(MODES.keys()), default="factory",
        help="运行模式 (默认 factory)",
    )
    args = parser.parse_args()
    await MODES[args.mode]()


if __name__ == "__main__":
    asyncio.run(main())
