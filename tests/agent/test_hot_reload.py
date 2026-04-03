from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from mindbot.builders import create_agent
from mindbot.config.schema import Config
from mindbot.context.models import ChatResponse, FinishReason, Message


class FakeLLM:
    def __init__(self, response_content: str) -> None:
        self._response_content = response_content

    async def chat(
        self,
        messages: list[Message],
        model: str | None = None,
        tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        return ChatResponse(content=self._response_content, finish_reason=FinishReason.STOP)

    async def chat_stream(
        self,
        messages: list[Message],
        model: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        yield self._response_content

    def bind_tools(self, tools: list[Any]) -> "FakeLLM":
        return self


@pytest.mark.asyncio
async def test_builder_includes_builtin_and_create_tool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MINDBOT_TOOLS_DIR", str(tmp_path / "dynamic-tools"))
    llm = FakeLLM(
        '{"name":"generated_echo","description":"Echo data","parameters_schema":{"type":"object","properties":{}},"implementation_type":"mock","implementation_ref":""}'
    )
    agent = create_agent(
        Config(agent={"model": "openai/test"}),
        llm=llm,
        with_memory=False,
    )

    assert agent.has_tool("read_file")
    assert agent.has_tool("create_tool")

    create_tool = agent.tool_registry.get("create_tool")
    assert create_tool is not None and create_tool.handler is not None

    result = await create_tool.handler(
        description="Generate a reusable echo tool",
        name_hint="generated_echo",
        parameters_schema={"type": "object", "properties": {}},
    )
    assert "generated_echo" in result

    agent.refresh_capabilities()
    assert agent.has_tool("generated_echo")


@pytest.mark.asyncio
async def test_reload_tools_restores_persisted_dynamic_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store_dir = tmp_path / "dynamic-tools"
    monkeypatch.setenv("MINDBOT_TOOLS_DIR", str(store_dir))

    llm = FakeLLM(
        '{"name":"persistent_echo","description":"Echo data","parameters_schema":{"type":"object","properties":{}},"implementation_type":"mock","implementation_ref":""}'
    )
    agent = create_agent(
        Config(agent={"model": "openai/test"}),
        llm=llm,
        with_memory=False,
        include_builtin_tools=False,
        enable_dynamic_tools=True,
    )

    create_tool = agent.tool_registry.get("create_tool")
    assert create_tool is not None and create_tool.handler is not None
    await create_tool.handler(description="Persist a tool", name_hint="persistent_echo")
    assert any(path.name == "persistent_echo.json" for path in store_dir.iterdir())

    reloaded_agent = create_agent(
        Config(agent={"model": "openai/test"}),
        llm=llm,
        with_memory=False,
        include_builtin_tools=False,
        enable_dynamic_tools=True,
    )

    loaded = await reloaded_agent.reload_tools()
    assert loaded >= 1
    assert reloaded_agent.has_tool("persistent_echo")
