from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from mindbot.builders import create_agent
from mindbot.config.schema import Config
from mindbot.context.models import ChatResponse, FinishReason, Message


class FakeLLM:
    async def chat(
        self,
        messages: list[Message],
        model: str | None = None,
        tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        return ChatResponse(content="ok", finish_reason=FinishReason.STOP)

    async def chat_stream(
        self,
        messages: list[Message],
        model: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        yield "ok"

    def bind_tools(self, tools: list[Any]) -> "FakeLLM":
        return self


@pytest.fixture()
def anyio_backend() -> str:
    return "asyncio"


def test_create_agent_uses_configured_workspace_for_builtin_tools(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "note.txt").write_text("hello", encoding="utf-8")

    agent = create_agent(
        Config(
            agent={
                "model": "openai/test",
                "workspace": str(workspace),
                "system_path_whitelist": [],
            }
        ),
        llm=FakeLLM(),
        with_memory=False,
        enable_dynamic_tools=False,
    )

    tools = {tool.name: tool for tool in agent.tool_registry.list_tools()}
    result = tools["read_file"].handler("note.txt")  # type: ignore[union-attr]

    assert "1|hello" in result


@pytest.mark.anyio
async def test_create_agent_passes_shell_execution_policy(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    agent = create_agent(
        Config(
            agent={
                "model": "openai/test",
                "workspace": str(workspace),
                "system_path_whitelist": [],
                "shell_execution": {"policy": "sandboxed"},
            }
        ),
        llm=FakeLLM(),
        with_memory=False,
        enable_dynamic_tools=False,
    )

    tools = {tool.name: tool for tool in agent.tool_registry.list_tools()}
    result = await tools["exec_command"].handler("pwd")  # type: ignore[union-attr]

    assert "does not yet provide an OS-level shell sandbox" in result
