"""Unit tests for :class:`mindbot.context.packer.ContextPacker`.

Covers core cognitive-workspace behaviours:

* Required items are always kept.
* Optional items compete by priority and salience.
* Empty/absent items free their budget for others.
* Compression callbacks are tried before dropping.
* Final messages come out in canonical source order regardless of
  pack order.
"""

from __future__ import annotations

import pytest

from mindbot.context.items import ContextItem
from mindbot.context.models import Message
from mindbot.context.packer import ContextPacker, PackerConfig
from mindbot.utils import estimate_tokens


def _msg(role: str, text: str) -> Message:
    m = Message(role=role, content=text)
    m.token_count = estimate_tokens(text)
    return m


def _item(
    name: str,
    source: str,
    text: str,
    *,
    priority: int = 50,
    salience: float = 0.5,
    required: bool = False,
    compress=None,
    role: str = "system",
) -> ContextItem:
    return ContextItem(
        name=name,
        source=source,  # type: ignore[arg-type]
        messages=[_msg(role, text)],
        priority=priority,
        salience=salience,
        required=required,
        compress=compress,
    )


@pytest.fixture()
def packer() -> ContextPacker:
    return ContextPacker(PackerConfig(response_reserve=0, min_item_tokens=4))


# ---------------------------------------------------------------------------
# Required items
# ---------------------------------------------------------------------------


class TestRequiredItems:
    def test_required_items_always_kept(self, packer: ContextPacker) -> None:
        items = [
            _item("system_identity", "system", "You are an assistant.", required=True, priority=100),
            _item("user_input", "user", "hello", required=True, priority=100, role="user"),
        ]
        result = packer.pack(items, total_budget=10_000)

        names = [it.name for it in result.kept_items]
        assert "system_identity" in names
        assert "user_input" in names
        assert not result.dropped_items

    def test_required_item_truncated_when_oversized(self) -> None:
        big = "word " * 1000
        item = _item("system_identity", "system", big, required=True, priority=100)
        # Tiny budget: required item must still fit by truncation.
        small_packer = ContextPacker(PackerConfig(response_reserve=0, min_item_tokens=4))
        result = small_packer.pack([item], total_budget=50)

        assert result.kept_items
        kept = result.kept_items[0]
        assert kept.name == "system_identity"
        assert kept.compressed
        assert kept.token_count <= 50


# ---------------------------------------------------------------------------
# Optional items: empty blocks yield budget
# ---------------------------------------------------------------------------


class TestEmptyYieldsBudget:
    def test_empty_skill_blocks_let_conversation_use_budget(
        self, packer: ContextPacker
    ) -> None:
        long_history = "abc " * 800  # large
        items = [
            _item("system_identity", "system", "sys", required=True, priority=100),
            _item(
                "conversation",
                "conversation",
                long_history,
                priority=40,
                salience=0.5,
            ),
            _item("user_input", "user", "current", required=True, priority=100, role="user"),
        ]
        result = packer.pack(items, total_budget=2000)

        assert any(it.name == "conversation" and not it.dropped for it in result.items)

    def test_dropped_low_priority_when_budget_tight(self, packer: ContextPacker) -> None:
        items = [
            _item("system_identity", "system", "sys", required=True, priority=100),
            _item(
                "skills_overview",
                "skill_overview",
                "skill " * 1000,  # large
                priority=50,
                salience=0.4,
            ),
            _item(
                "skills_detail",
                "skill_detail",
                "task hint",
                priority=70,
                salience=0.9,
            ),
            _item("user_input", "user", "hi", required=True, priority=100, role="user"),
        ]
        result = packer.pack(items, total_budget=400)

        decisions = {it.name: it for it in result.items}
        # Higher-priority skill_detail should beat skills_overview when tight.
        assert not decisions["skills_detail"].dropped
        assert decisions["skills_overview"].dropped


# ---------------------------------------------------------------------------
# Compression callbacks
# ---------------------------------------------------------------------------


class TestCompression:
    def test_compress_callback_used_before_drop(self, packer: ContextPacker) -> None:
        big = "word " * 500

        def compress(target: int) -> list[Message]:
            tiny = _msg("system", "compressed")
            return [tiny]

        items = [
            _item("system_identity", "system", "sys", required=True, priority=100),
            ContextItem(
                name="memory",
                source="memory",
                messages=[_msg("system", big)],
                priority=60,
                salience=0.5,
                compress=compress,
            ),
            _item("user_input", "user", "hi", required=True, priority=100, role="user"),
        ]
        result = packer.pack(items, total_budget=200)

        memory = next(it for it in result.items if it.name == "memory")
        assert not memory.dropped
        assert memory.compressed
        assert memory.messages[0].content == "compressed"


# ---------------------------------------------------------------------------
# Canonical ordering
# ---------------------------------------------------------------------------


class TestCanonicalOrder:
    def test_messages_emitted_in_canonical_source_order(self, packer: ContextPacker) -> None:
        items = [
            _item("user_input", "user", "USR", required=True, priority=100, role="user"),
            _item("conversation", "conversation", "CONV", priority=40, role="user"),
            _item("memory", "memory", "MEM", priority=60),
            _item("system_identity", "system", "SYS", required=True, priority=100),
        ]
        result = packer.pack(items, total_budget=10_000)

        contents = [m.content for m in result.messages]
        # Canonical send order: system → memory → conversation → user
        assert contents == ["SYS", "MEM", "CONV", "USR"]


# ---------------------------------------------------------------------------
# Response reserve
# ---------------------------------------------------------------------------


class TestResponseReserve:
    def test_response_reserve_subtracted_from_budget(self) -> None:
        items = [_item("user_input", "user", "hi", required=True, priority=100, role="user")]
        packer = ContextPacker(PackerConfig(response_reserve=512))
        result = packer.pack(items, total_budget=2048)

        assert result.budget == 2048 - 512

    def test_per_call_response_reserve_overrides_default(self) -> None:
        items = [_item("user_input", "user", "hi", required=True, priority=100, role="user")]
        packer = ContextPacker(PackerConfig(response_reserve=512))
        result = packer.pack(items, total_budget=2048, response_reserve=0)

        assert result.budget == 2048
