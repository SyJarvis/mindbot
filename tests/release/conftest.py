"""Fixtures for real SDK release functional tests."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest


def _functional_tests_enabled() -> bool:
    return os.environ.get("MINDBOT_RUN_SDK_FUNCTIONAL") == "1"


def _load_release_config(tmp_path: Path):
    if not _functional_tests_enabled():
        pytest.skip(
            "Set MINDBOT_RUN_SDK_FUNCTIONAL=1 to run real SDK functional tests"
        )

    from mindbot.config.loader import load_config
    from mindbot.config.schema import (
        AgentConfig,
        Config,
        EndpointConfig,
        LoggingConfig,
        MemoryConfig,
        ProviderInstanceConfig,
        VectorMemoryConfig,
    )

    config_path = os.environ.get("MINDBOT_SDK_TEST_CONFIG")
    if config_path:
        config = load_config(Path(config_path).expanduser())
    else:
        model_ref = (
            os.environ.get("MINDBOT_SDK_TEST_MODEL")
            or os.environ.get("MINDBOT_MODELS")
            or ""
        ).strip()
        base_url = (
            os.environ.get("MINDBOT_SDK_TEST_BASE_URL")
            or os.environ.get("MINDBOT_BASE_URL")
            or ""
        ).strip()
        if not model_ref or not base_url:
            pytest.fail(
                "Set MINDBOT_SDK_TEST_CONFIG, or set both "
                "MINDBOT_SDK_TEST_MODEL and MINDBOT_SDK_TEST_BASE_URL"
            )

        provider_type = (
            os.environ.get("MINDBOT_SDK_TEST_PROVIDER")
            or os.environ.get("MINDBOT_PROVIDER")
            or "openai"
        ).strip()
        instance = (
            os.environ.get("MINDBOT_SDK_TEST_INSTANCE")
            or os.environ.get("MINDBOT_PLATFORM")
            or "sdk-test"
        )
        instance = instance.strip() or "sdk-test"
        model_ref = model_ref.split(",", 1)[0].strip()
        model_id = model_ref.split("/", 1)[1] if "/" in model_ref else model_ref

        config = Config(
            agent=AgentConfig(
                model=f"{instance}/{model_id}",
                max_tokens=1024,
                max_tool_iterations=5,
                memory_top_k=0,
            ),
            providers={
                instance: ProviderInstanceConfig(
                    type=provider_type,
                    endpoints=[
                        EndpointConfig(
                            base_url=base_url,
                            api_key=(
                                os.environ.get("MINDBOT_SDK_TEST_API_KEY")
                                or os.environ.get("MINDBOT_API_KEY")
                                or ""
                            ),
                            models=[model_id],
                        )
                    ],
                )
            },
            memory=MemoryConfig(
                vector=VectorMemoryConfig(enabled=False),
            ),
            logging=LoggingConfig(file=False),
        )

    _isolate_config(config, tmp_path)
    return config


def _isolate_config(config, tmp_path: Path) -> None:
    """Force every writable SDK path into the pytest temporary directory."""
    from mindbot.config.schema import ToolAskMode

    config.routing.auto = False
    config.agent.workspace = str(tmp_path / "workspace")
    config.agent.system_path_whitelist = [str(tmp_path)]
    config.agent.trusted_paths = []
    config.agent.memory_top_k = 0
    config.agent.max_tool_iterations = 5
    config.agent.approval.ask = ToolAskMode.OFF

    config.memory.base_path = str(tmp_path / "memory")
    config.memory.content_path = str(tmp_path / "memory" / "content")
    config.memory.storage_path = str(tmp_path / "memory.db")
    config.memory.markdown_path = str(tmp_path / "memory-markdown")
    config.memory.vector.enabled = False
    config.memory.vector.persist_path = str(tmp_path / "vectors")

    config.session_journal.enabled = True
    config.session_journal.path = str(tmp_path / "journal")
    config.logging.file = False


@pytest.fixture()
def sdk_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return _load_release_config(tmp_path)


@pytest.fixture()
def sdk_bot(sdk_config):
    from mindbot import MindBot

    bot = MindBot(config=sdk_config)
    if bot._agent is None:
        pytest.fail(f"Real SDK agent initialization failed: {bot._agent_error}")
    return bot
