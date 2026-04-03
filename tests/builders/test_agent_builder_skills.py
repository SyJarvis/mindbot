from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from mindbot.builders import create_agent
from mindbot.config.schema import Config
from mindbot.context.models import ChatResponse, FinishReason, Message


class FakeLLM:
    def __init__(self, response_content: str = "ok") -> None:
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


def test_create_agent_wires_skill_registry_into_input_builder(tmp_path: Path) -> None:
    skill_root = tmp_path / "skills"
    skill_dir = skill_root / "python-helper"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                "name: python-helper",
                "description: Answers Python questions",
                "when_to_use: Use for Python code help",
                "---",
                "",
                "# Python Helper",
                "",
                "Prefer Python-specific guidance.",
            ]
        ),
        encoding="utf-8",
    )

    agent = create_agent(
        Config(
            agent={"model": "openai/test"},
            skills={
                "enabled": True,
                "skill_dirs": [str(skill_root)],
                "max_visible": 4,
                "max_detail_load": 1,
            },
        ),
        llm=FakeLLM(),
        with_memory=False,
        include_builtin_tools=False,
        enable_dynamic_tools=False,
    )

    messages = agent._get_session_input_builder("skill-session").build("Need help with Python functions")

    assert messages[0].role == "system"
    assert "Available skills:" in messages[0].content
    assert "Selected skill: python-helper" in messages[1].content

