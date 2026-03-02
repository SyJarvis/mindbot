#!/usr/bin/env python3
"""Example: define tools with @tool, register with MindBot, and run a chat that uses them.

Run (uses ~/.mindbot/settings.yaml by default; requires Ollama or your provider in config)::

    cd /path/to/mindbot && python -m examples.tool_example

Override config path::

    python -m examples.tool_example --config /path/to/settings.yaml
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

# ---------------------------------------------------------------------------
# 1. Define tools with the @tool decorator
# ---------------------------------------------------------------------------

from mindbot.capability.backends.tooling import tool


@tool()
def get_weather(city: str, unit: str = "celsius") -> str:
    """Get current weather for a city. Use unit 'celsius' or 'fahrenheit'."""
    # Simulated response; replace with real API in production
    return f"Weather in {city}: 22°{unit}, partly cloudy."


@tool(name="echo")
def echo_message(message: str) -> str:
    """Echo back the given message. Useful for testing tool calling."""
    return message


@tool(description="Compute the sum of two numbers.")
def add(a: int, b: int) -> str:
    """Add two integers and return the result as string."""
    return str(a + b)


# ---------------------------------------------------------------------------
# 2. Build config and run chat with tools
# ---------------------------------------------------------------------------


def make_config(config_path: Path | None):
    """Load config from file or use minimal defaults (Ollama local)."""
    from mindbot.config.loader import load_config
    from mindbot.config.schema import Config, AgentConfig, ProviderConfig

    if config_path and config_path.exists():
        return load_config(config_path)
    # Minimal config: Ollama at localhost (no config file required)
    return Config(
        agent=AgentConfig(model="ollama/qwen3-vl:8b", max_tool_iterations=10),
        providers={
            "ollama": ProviderConfig(base_url="http://localhost:11434", api_key=""),
        },
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description="MindBot tool usage example")
    default_config = Path.home() / ".mindbot" / "settings.yaml"
    parser.add_argument(
        "--config",
        type=Path,
        default=default_config,
        help=f"Path to settings.yaml (default: {default_config})",
    )
    parser.add_argument(
        "--message",
        type=str,
        default="北京今天天气怎么样？用 get_weather 查一下。",
        help="User message to send",
    )
    args = parser.parse_args()

    config = make_config(args.config)
    from mindbot import MindBot

    bot = MindBot(config=config)

    # 3. Define the tools to use for this conversation
    my_tools = [get_weather, echo_message, add]

    print("Tools:", [t.name for t in my_tools])
    print("User:", args.message)
    print("-" * 60)

    # 4. Chat with tools passed directly as a parameter
    result = await bot.chat(args.message, tools=my_tools)

    print("Final response:", result.content)
    print("Stop reason:", result.stop_reason)


if __name__ == "__main__":
    asyncio.run(main())
