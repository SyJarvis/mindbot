"""Unit tests for agent.input_builder.InputBuilder.

Covers:
- build(): block ordering, memory injection, intent_state placement
- build_messages alias
- memory population (with / without MemoryManager)
- system prompt initialisation
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from mindbot.agent.input_builder import InputBuilder
from mindbot.config.schema import ContextConfig, SkillsConfig
from mindbot.context.manager import ContextManager
from mindbot.skills.models import SkillDefinition
from mindbot.skills.registry import SkillRegistry


# ---------------------------------------------------------------------------
# Lightweight stubs
# ---------------------------------------------------------------------------


@dataclass
class FakeMemoryChunk:
    text: str
    id: str = "chunk-1"


class FakeMemoryManager:
    def __init__(self, chunks: list[FakeMemoryChunk] | None = None) -> None:
        self._chunks = chunks or []

    def search(self, query: str, top_k: int = 5, source: str | None = None) -> list[FakeMemoryChunk]:
        return self._chunks[:top_k]

    def append_to_short_term(self, content: str, **kw: Any) -> list[Any]:
        return []


class FailingMemoryManager(FakeMemoryManager):
    def search(self, query: str, top_k: int = 5, source: str | None = None) -> list[FakeMemoryChunk]:
        raise RuntimeError("memory down")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def ctx() -> ContextManager:
    return ContextManager(ContextConfig(max_tokens=4000))


@pytest.fixture()
def memory_with_chunks() -> FakeMemoryManager:
    return FakeMemoryManager([
        FakeMemoryChunk(text="User likes Python", id="c1"),
        FakeMemoryChunk(text="Previous topic: testing", id="c2"),
    ])


# ---------------------------------------------------------------------------
# build()
# ---------------------------------------------------------------------------


class TestBuild:

    def test_basic_build_returns_user_message(self, ctx: ContextManager) -> None:
        builder = InputBuilder(context=ctx)
        msgs = builder.build("hello")

        assert len(msgs) == 1
        assert msgs[-1].role == "user"
        assert msgs[-1].content == "hello"

    def test_block_order_system_skills_memory_conversation_intent_user(
        self, ctx: ContextManager, memory_with_chunks: FakeMemoryManager,
    ) -> None:
        ctx.set_system_identity("You are helpful.")
        ctx.add_conversation_message("user", "earlier")
        ctx.add_conversation_message("assistant", "earlier reply")
        registry = SkillRegistry.from_skills([
            SkillDefinition(
                name="python-helper",
                description="Answers Python questions",
                when_to_use="Use for Python programming questions",
                body="Prefer Python-specific guidance.",
                loaded_from="builtin",
                skill_dir=Path("/tmp/python-helper"),
            )
        ])

        builder = InputBuilder(
            context=ctx,
            memory=memory_with_chunks,
            skill_registry=registry,
            skills_config=SkillsConfig(
                max_visible=4,
                max_detail_load=1,
                trigger_mode="explicit-only",
            ),
        )
        msgs = builder.build("new question", intent_state="Be concise.")

        roles = [m.role for m in msgs]
        assert roles[0] == "system"      # system_identity
        assert roles[1] == "system"      # skills_overview
        assert roles[2] == "system"      # memory
        assert roles[3] == "user"        # conversation
        assert roles[4] == "assistant"   # conversation
        assert roles[5] == "system"      # intent_state
        assert roles[6] == "user"        # user_input
        assert msgs[-1].content == "new question"
        assert msgs[-2].content == "Be concise."

    def test_intent_state_omitted_when_none(self, ctx: ContextManager) -> None:
        builder = InputBuilder(context=ctx, system_prompt="sys")
        msgs = builder.build("hi")

        roles = [m.role for m in msgs]
        assert roles == ["system", "user"]

    def test_memory_block_populated(
        self, ctx: ContextManager, memory_with_chunks: FakeMemoryManager,
    ) -> None:
        builder = InputBuilder(context=ctx, memory=memory_with_chunks)
        builder.build("search query")

        mem_msgs = ctx.get_block("memory").messages
        assert len(mem_msgs) == 1
        assert "User likes Python" in mem_msgs[0].content

    def test_memory_search_failure_is_graceful(self, ctx: ContextManager) -> None:
        builder = InputBuilder(context=ctx, memory=FailingMemoryManager())
        msgs = builder.build("hello")

        assert ctx.get_block("memory").messages == []
        assert len(msgs) >= 1

    def test_system_prompt_sets_identity(self, ctx: ContextManager) -> None:
        builder = InputBuilder(context=ctx, system_prompt="I am a bot.")
        msgs = builder.build("hello")

        assert msgs[0].role == "system"
        assert msgs[0].content == "I am a bot."

    def test_user_input_block_refreshed_between_calls(self, ctx: ContextManager) -> None:
        builder = InputBuilder(context=ctx)

        builder.build("first")
        assert ctx.get_block("user_input").messages[0].content == "first"

        builder.build("second")
        assert len(ctx.get_block("user_input").messages) == 1
        assert ctx.get_block("user_input").messages[0].content == "second"

    def test_build_messages_delegates_to_build(self, ctx: ContextManager) -> None:
        builder = InputBuilder(context=ctx)
        msgs1 = builder.build("hello")
        # Reset user_input so second call assembles the same
        ctx.clear_user_input()
        msgs2 = builder.build_messages("hello")
        assert [m.content for m in msgs1] == [m.content for m in msgs2]

    def test_context_property(self, ctx: ContextManager) -> None:
        builder = InputBuilder(context=ctx)
        assert builder.context is ctx

    def test_reads_blocks_directly_not_via_prepare_for_llm(self, ctx: ContextManager) -> None:
        """InputBuilder should NOT call prepare_for_llm(); it reads blocks itself."""
        call_log: list[str] = []
        original = ctx.prepare_for_llm

        def tracking_prepare() -> list:
            call_log.append("prepare_for_llm")
            return original()

        ctx.prepare_for_llm = tracking_prepare  # type: ignore[assignment]

        builder = InputBuilder(context=ctx, system_prompt="sys")
        builder.build("hello")
        assert "prepare_for_llm" not in call_log

    def test_skills_blocks_populated_for_matching_query(self, ctx: ContextManager) -> None:
        registry = SkillRegistry.from_skills([
            SkillDefinition(
                name="python-helper",
                description="Answers Python questions",
                when_to_use="Use for Python programming questions",
                body="Prefer Python-specific guidance.",
                loaded_from="builtin",
                skill_dir=Path("/tmp/python-helper"),
            )
        ])
        builder = InputBuilder(
            context=ctx,
            skill_registry=registry,
            skills_config=SkillsConfig(max_visible=4, max_detail_load=1),
        )

        msgs = builder.build("Need help with Python functions")

        assert "Available skills:" in ctx.get_block("skills_overview").messages[0].content
        assert "Selected skill: python-helper" in ctx.get_block("skills_detail").messages[0].content
        assert msgs[0].content.startswith("Available skills:")
        assert msgs[1].content.startswith("Selected skill:")

    def test_skills_detail_omitted_when_nothing_matches(self, ctx: ContextManager) -> None:
        registry = SkillRegistry.from_skills([
            SkillDefinition(
                name="python-helper",
                description="Answers Python questions",
                when_to_use="Use for Python programming questions",
                body="Prefer Python-specific guidance.",
                loaded_from="builtin",
                skill_dir=Path("/tmp/python-helper"),
            )
        ])
        builder = InputBuilder(
            context=ctx,
            skill_registry=registry,
            skills_config=SkillsConfig(always_include=["python-helper"], max_visible=4, max_detail_load=1),
        )

        builder.build("Tell me a joke")

        assert "Available skills:" in ctx.get_block("skills_overview").messages[0].content
        assert ctx.get_block("skills_detail").messages == []
