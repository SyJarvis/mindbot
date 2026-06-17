"""Functional check executed with an installed MindBot wheel."""

from __future__ import annotations

import asyncio
import importlib.resources
import os
import tempfile
import uuid
from pathlib import Path


def _load_isolated_config(root: Path):
    from mindbot.config.loader import load_config
    from mindbot.config.schema import (
        AgentConfig,
        Config,
        EndpointConfig,
        ProviderInstanceConfig,
        ToolAskMode,
    )

    config_path = os.environ.get("MINDBOT_SDK_TEST_CONFIG")
    if config_path:
        config = load_config(Path(config_path).expanduser())
    else:
        provider_type = os.environ.get("MINDBOT_PROVIDER", "openai")
        instance = os.environ.get("MINDBOT_PLATFORM", "sdk-test")
        model_id = os.environ.get("MINDBOT_MODELS", "").split(",", 1)[0].strip()
        base_url = os.environ.get("MINDBOT_BASE_URL", "").strip()
        if not model_id or not base_url:
            raise RuntimeError(
                "Set MINDBOT_SDK_TEST_CONFIG or source provider settings "
                "with MINDBOT_MODELS and MINDBOT_BASE_URL"
            )
        config = Config(
            agent=AgentConfig(model=f"{instance}/{model_id}"),
            providers={
                instance: ProviderInstanceConfig(
                    type=provider_type,
                    endpoints=[
                        EndpointConfig(
                            base_url=base_url,
                            api_key=os.environ.get("MINDBOT_API_KEY", ""),
                            models=[model_id],
                        )
                    ],
                )
            },
        )
    config.routing.auto = False
    config.agent.workspace = str(root / "workspace")
    config.agent.system_path_whitelist = [str(root)]
    config.agent.trusted_paths = []
    config.agent.memory_top_k = 0
    config.agent.max_tool_iterations = 3
    config.agent.approval.ask = ToolAskMode.OFF
    config.memory.base_path = str(root / "memory")
    config.memory.content_path = str(root / "memory" / "content")
    config.memory.storage_path = str(root / "memory.db")
    config.memory.markdown_path = str(root / "memory-markdown")
    config.memory.vector.enabled = False
    config.memory.vector.persist_path = str(root / "vectors")
    config.session_journal.enabled = True
    config.session_journal.path = str(root / "journal")
    config.logging.file = False
    return config


async def _main() -> None:
    import mindbot
    from mindbot import Config, MindBot
    from mindbot.agent.models import StopReason

    module_path = Path(mindbot.__file__).resolve()
    repository_root = os.environ.get("MINDBOT_REPOSITORY_ROOT")
    if repository_root:
        source_root = (Path(repository_root) / "src").resolve()
        if module_path.is_relative_to(source_root):
            raise AssertionError(f"Imported source tree instead of wheel: {module_path}")

    system_prompt = importlib.resources.files("mindbot.templates").joinpath("SYSTEM.md")
    if not system_prompt.is_file():
        raise AssertionError("Installed wheel is missing mindbot/templates/SYSTEM.md")

    with tempfile.TemporaryDirectory(prefix="mindbot-installed-sdk-") as tmp:
        root = Path(tmp)
        os.environ["HOME"] = str(root / "home")
        config = _load_isolated_config(root)
        if not isinstance(config, Config):
            raise AssertionError("Config file did not produce mindbot.Config")

        bot = MindBot(config=config)
        response = await bot.chat(
            "请用一句中文说明当前安装包可以正常对话。",
            session_id=f"wheel-{uuid.uuid4().hex}",
        )

        if response.stop_reason != StopReason.COMPLETED:
            raise AssertionError(f"Unexpected stop reason: {response.stop_reason}")
        if not response.content.strip():
            raise AssertionError("Installed SDK returned empty content")

    print(f"installed-sdk-ok version={mindbot.__version__} module={module_path}")


if __name__ == "__main__":
    asyncio.run(_main())
