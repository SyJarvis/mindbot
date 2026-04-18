#!/usr/bin/env python3
"""Example 12: 多模态图片理解 (Vision)。

演示：
- 构建包含图片的 Message (使用 TextPart + ImagePart)
- 直接使用底层组件进行图片理解
- 路由器自动检测图片并选择支持 vision 的模型
- 支持本地图片文件和远程 URL

Run::

    python -m examples.12_multimodal_vision
    python -m examples.12_multimodal_vision --image unsloth.png
    python -m examples.12_multimodal_vision --image https://example.com/image.png
"""

from __future__ import annotations

import argparse
import asyncio
import base64
from pathlib import Path

from mindbot.context.models import Message, TextPart, ImagePart


def load_image_source(source: str) -> tuple[str, str]:
    """Load image from file path or URL.

    Returns:
        (data, mime_type) tuple. For URLs, data is the URL string.
        For files, data is base64-encoded string.
    """
    if source.startswith(("http://", "https://")):
        # Remote URL - provider handles fetch
        mime = "image/png"
        return source, mime

    # Local file
    path = Path(source).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Image file not found: {path}")

    data = base64.b64encode(path.read_bytes()).decode()
    # Guess mime type from extension
    ext = path.suffix.lower()
    mime_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    mime = mime_map.get(ext, "image/png")
    return data, mime


def make_config(config_path: Path | None):
    """Create config for vision-capable model."""
    from mindbot.config.loader import load_config
    from mindbot.config.schema import AgentConfig, Config, ProviderConfig

    if config_path and config_path.exists():
        return load_config(config_path)

    # Default: use Ollama with qwen2.5vl (vision model)
    return Config(
        agent=AgentConfig(model="ollama/qwen2.5vl:7b"),
        providers={
            "ollama": ProviderConfig(
                base_url="http://localhost:11434",
                api_key="",
            )
        },
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description="MindBot 多模态图片理解示例")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path.home() / ".mindbot" / "settings.json",
        help="配置文件路径",
    )
    parser.add_argument(
        "--image",
        type=str,
        default="unsloth.png",
        help="图片路径 (本地文件或 URL)",
    )
    parser.add_argument(
        "--question",
        type=str,
        default="提取图片里的文本内容。",
        help="对图片的提问",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="覆盖模型 (需要是 Vision 模型，如 openai/gpt-4o, ollama/llava)",
    )
    args = parser.parse_args()

    config = make_config(args.config)
    if args.model:
        config.agent.model = args.model

    # 加载图片
    print(f"Loading image: {args.image}")
    image_data, mime_type = load_image_source(args.image)

    # 构建多模态消息
    message = Message(
        role="user",
        content=[
            TextPart(text=args.question),
            ImagePart(data=image_data, mime_type=mime_type),
        ],
    )

    print(f"\nUser: {args.question}")
    print("-" * 60)

    # 使用 Provider 进行多模态对话
    # 路由器会自动检测图片并选择支持 vision 的模型
    from mindbot.builders import create_llm

    provider = create_llm(config)
    response = await provider.chat([message])

    print(f"Assistant: {response.content}")
    print(f"\nStop reason: {response.finish_reason}")

    if response.usage:
        print(f"Tokens: prompt={response.usage.prompt_tokens}, completion={response.usage.completion_tokens}, total={response.usage.total_tokens}")


if __name__ == "__main__":
    asyncio.run(main())