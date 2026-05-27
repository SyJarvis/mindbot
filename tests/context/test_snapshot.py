"""Unit tests for :class:`mindbot.context.snapshot.ConversationContinuitySnapshot`.

Covers:
* Model initialisation and empty detection.
* Rendering to structured system message text.
* LLM response parsing into snapshot fields.
* Packer integration — snapshot item survives tight budget.
* InputBuilder produces snapshot item when snapshot is set.
"""

from __future__ import annotations

import pytest

from mindbot.context.items import ContextItem
from mindbot.context.models import Message
from mindbot.context.packer import ContextPacker, PackerConfig
from mindbot.context.snapshot import (
    ConversationContinuitySnapshot,
    _parse_snapshot,
    update_snapshot_from_messages,
)
from mindbot.utils import estimate_tokens


def _msg(role: str, text: str) -> Message:
    m = Message(role=role, content=text)
    m.token_count = estimate_tokens(text)
    return m


def _truncate_messages_factory(messages: list[Message]):
    snapshot = list(messages)

    def _compress(target: int) -> list[Message]:
        return _truncate_to_budget(snapshot, target)

    return _compress


def _truncate_to_budget(messages: list[Message], target: int) -> list[Message]:
    if target <= 0 or not messages:
        return []
    kept: list[Message] = []
    used = 0
    for msg in reversed(messages):
        cost = msg.token_count if msg.token_count > 0 else estimate_tokens(msg.text)
        if used + cost > target:
            break
        kept.append(msg)
        used += cost
    kept.reverse()
    return kept


def _snap_item(snapshot: ConversationContinuitySnapshot) -> ContextItem:
    snap_msg = snapshot.to_message()
    return ContextItem(
        name="conversation_continuity",
        source="conversation_continuity",  # type: ignore[arg-type]
        messages=[snap_msg],
        priority=55,
        salience=0.85,
        cache_scope="session",
        compress=_truncate_messages_factory([snap_msg]),
    )


# ---------------------------------------------------------------------------
# Model initialisation & empty detection
# ---------------------------------------------------------------------------


class TestSnapshotModel:
    def test_default_is_empty(self) -> None:
        snap = ConversationContinuitySnapshot()
        assert snap.is_empty

    def test_task_makes_non_empty(self) -> None:
        snap = ConversationContinuitySnapshot(current_task="Build a wiki system")
        assert not snap.is_empty

    def test_decision_makes_non_empty(self) -> None:
        snap = ConversationContinuitySnapshot(
            confirmed_decisions=["Use markdown for wiki pages"]
        )
        assert not snap.is_empty

    def test_focus_makes_non_empty(self) -> None:
        snap = ConversationContinuitySnapshot(current_focus="implementing Ingestor")
        assert not snap.is_empty

    def test_binding_makes_non_empty(self) -> None:
        snap = ConversationContinuitySnapshot(
            reference_bindings={"this": "the Ingestor module"}
        )
        assert not snap.is_empty


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


class TestSnapshotRender:
    def test_render_full_snapshot(self) -> None:
        snap = ConversationContinuitySnapshot(
            current_task="Build a wiki system for MindBot",
            confirmed_decisions=["Use markdown for wiki pages", "Store in ~/.mindbot/wiki"],
            current_focus="Implementing the WikiEngine Ingestor",
            open_questions=["How should cross-references be formatted?"],
            next_likely_action="Create the WikiPage data model",
            reference_bindings={
                "this": "the Ingestor module",
                "that": "the SCHEMA.md convention",
            },
        )
        rendered = snap.render()

        assert "Current task: Build a wiki system" in rendered
        assert "Use markdown for wiki pages" in rendered
        assert "Store in ~/.mindbot/wiki" in rendered
        assert "Current focus: Implementing the WikiEngine Ingestor" in rendered
        assert "How should cross-references be formatted?" in rendered
        assert "Next likely action: Create the WikiPage data model" in rendered
        assert '"this" → the Ingestor module' in rendered
        assert '"that" → the SCHEMA.md convention' in rendered
        assert rendered.startswith("[Conversation continuity]")

    def test_render_partial_snapshot(self) -> None:
        snap = ConversationContinuitySnapshot(
            current_task="Fix a bug",
            current_focus="The streaming output is broken",
        )
        rendered = snap.render()

        assert "Current task: Fix a bug" in rendered
        assert "Current focus: The streaming output is broken" in rendered
        assert "Confirmed decisions:" not in rendered
        assert "Open questions:" not in rendered
        assert "Reference bindings:" not in rendered

    def test_render_empty_snapshot_produces_header_only(self) -> None:
        snap = ConversationContinuitySnapshot()
        rendered = snap.render()
        assert rendered == "[Conversation continuity]\n"

    def test_to_message_has_token_count(self) -> None:
        snap = ConversationContinuitySnapshot(
            current_task="Build a wiki system",
            current_focus="implementing",
        )
        msg = snap.to_message()
        assert msg.role == "system"
        assert msg.token_count > 0
        assert "Build a wiki system" in msg.text


# ---------------------------------------------------------------------------
# LLM response parsing
# ---------------------------------------------------------------------------


class TestSnapshotParsing:
    def test_parse_full_response(self) -> None:
        text = (
            "Current task: Implement a cache layer\n"
            "Confirmed decisions:\n"
            "- Use Redis for caching\n"
            "- TTL of 300 seconds\n"
            "Current focus: Writing the CacheManager class\n"
            "Open questions:\n"
            "- Should we support cache warming?\n"
            "- What eviction policy?\n"
            "Next likely action: Write unit tests for CacheManager\n"
            "Reference bindings:\n"
            '- "this" → the cache layer\n'
            '- "next step" → test coverage\n'
        )
        snap = _parse_snapshot(text)

        assert snap.current_task == "Implement a cache layer"
        assert snap.confirmed_decisions == ["Use Redis for caching", "TTL of 300 seconds"]
        assert snap.current_focus == "Writing the CacheManager class"
        assert snap.open_questions == [
            "Should we support cache warming?",
            "What eviction policy?",
        ]
        assert snap.next_likely_action == "Write unit tests for CacheManager"
        assert snap.reference_bindings == {
            "this": "the cache layer",
            "next step": "test coverage",
        }

    def test_parse_minimal_response(self) -> None:
        text = (
            "Current task: Debug\n"
            "Confirmed decisions:\n"
            "Current focus: testing\n"
            "Open questions:\n"
            "Next likely action: run tests\n"
            "Reference bindings:\n"
        )
        snap = _parse_snapshot(text)

        assert snap.current_task == "Debug"
        assert snap.confirmed_decisions == []
        assert snap.current_focus == "testing"
        assert snap.open_questions == []
        assert snap.next_likely_action == "run tests"
        assert snap.reference_bindings == {}

    def test_parse_bindings_arrow_variants(self) -> None:
        text = (
            "Current task: x\n"
            "Current focus: y\n"
            "Reference bindings:\n"
            '- "this" → the main module\n'
            '- that → another thing\n'
        )
        snap = _parse_snapshot(text)
        assert snap.reference_bindings == {
            "this": "the main module",
            "that": "another thing",
        }

    def test_parse_preserves_updated_at(self) -> None:
        snap = _parse_snapshot("Current task: hello\n\n\n")
        assert snap.updated_at > 0


# ---------------------------------------------------------------------------
# Packer integration
# ---------------------------------------------------------------------------


@pytest.fixture()
def packer() -> ContextPacker:
    return ContextPacker(PackerConfig(response_reserve=0, min_item_tokens=4))


class TestSnapshotPacker:
    def test_snapshot_survives_above_conversation(self, packer: ContextPacker) -> None:
        """Snapshot (priority 55) keeps while conversation (40) drops."""
        snap = ConversationContinuitySnapshot(
            current_task="Build wiki",
            current_focus="Ingestor",
        )
        snap_item = _snap_item(snap)

        conv_item = ContextItem(
            name="conversation",
            source="conversation",  # type: ignore[arg-type]
            messages=[_msg("user", "hi"), _msg("assistant", "hello" * 40)],
            priority=40,
            salience=0.5,
        )

        required = ContextItem(
            name="user_input",
            source="user",  # type: ignore[arg-type]
            messages=[_msg("user", "next?")],
            priority=100,
            salience=1.0,
            required=True,
        )

        result = packer.pack(
            [snap_item, conv_item, required],
            total_budget=30,
        )

        kept_names = [it.name for it in result.kept_items]
        assert "conversation_continuity" in kept_names, "snapshot should survive"
        assert "user_input" in kept_names

    def test_snapshot_appears_before_conversation_in_output(self, packer: ContextPacker) -> None:
        """Canonical order places continuity (5) before conversation (6)."""
        snap = ConversationContinuitySnapshot(
            current_task="Order test",
            current_focus="checking",
        )
        snap_item = _snap_item(snap)
        conv_item = ContextItem(
            name="conversation",
            source="conversation",  # type: ignore[arg-type]
            messages=[_msg("user", "hello"), _msg("assistant", "hi")],
            priority=40,
            salience=0.5,
        )

        result = packer.pack(
            [conv_item, snap_item],
            total_budget=2000,
        )

        text = "\n".join(m.text for m in result.messages)
        continuity_pos = text.index("Current task:")
        conv_pos = text.index("hello")
        assert continuity_pos < conv_pos, (
            "continuity snapshot should appear before conversation"
        )

    def test_snapshot_compresses_when_tight(self, packer: ContextPacker) -> None:
        """Under tight budget the snapshot survives (priority beats conversation)."""
        snap = ConversationContinuitySnapshot(
            current_task="Build a very complex system with many details",
            confirmed_decisions=["Choose Python"],
        )
        snap_item = _snap_item(snap)

        conv = ContextItem(
            name="conversation",
            source="conversation",  # type: ignore[arg-type]
            messages=[_msg("user", "lo " * 50)],
            priority=40,
            salience=0.5,
        )

        user = ContextItem(
            name="user_input",
            source="user",  # type: ignore[arg-type]
            messages=[_msg("user", "go")],
            priority=100,
            required=True,
            salience=1.0,
        )

        # Budget fits user + snapshot but not conversation.
        snap_tokens = snap_item.token_count
        result = packer.pack([snap_item, conv, user], total_budget=snap_tokens + 10)

        kept_names = [it.name for it in result.kept_items]
        assert "conversation_continuity" in kept_names


# ---------------------------------------------------------------------------
# update_snapshot_from_messages
# ---------------------------------------------------------------------------


class StubLLM:
    def __init__(self, reply: str) -> None:
        self._reply = reply
        self.calls: list[list[Message]] = []

    async def chat(self, messages: list[Message], **kwargs) -> object:
        self.calls.append(messages)
        return _StubResponse(self._reply)


class _StubResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class FailingStubLLM:
    async def chat(self, messages: list[Message], **kwargs) -> object:
        raise RuntimeError("injected failure")


_MULTI_TURN_MSGS: list[Message] = [
    _msg("user", "I'm building a wiki system for MindBot."),
    _msg("assistant", "That sounds great! What approach are you taking?"),
    _msg("user", "Using markdown files, stored under ~/.mindbot/wiki."),
    _msg("assistant", "Markdown is a solid choice for a local wiki."),
    _msg("user", "Let's start with the Ingestor module."),
    _msg("assistant", "Ok, the Ingestor will read source files and create wiki pages."),
    _msg("user", "Should we use an LLM for the extraction step?"),
    _msg("assistant", "Yes, using the LLM will produce better key-info extraction."),
]


_SNAPSHOT_REPLY = (
    "Current task: Build a wiki system for MindBot\n"
    "Confirmed decisions:\n"
    "- Use markdown files for wiki pages\n"
    "- Store wiki under ~/.mindbot/wiki\n"
    "- Start with Ingestor module\n"
    "Current focus: Implementing the Ingestor module\n"
    "Open questions:\n"
    "- Should we use LLM for extraction?\n"
    "Next likely action: Implement the key-info extraction step\n"
    "Reference bindings:\n"
    '- "this" → the Ingestor module\n'
    '- "it" → markdown-based wiki\n'
)


class TestUpdateSnapshotFromMessages:
    @pytest.mark.asyncio
    async def test_produces_non_empty_snapshot(self) -> None:
        llm = StubLLM(_SNAPSHOT_REPLY)
        snap = await update_snapshot_from_messages(
            llm, None, _MULTI_TURN_MSGS
        )
        assert not snap.is_empty
        assert snap.current_task == "Build a wiki system for MindBot"
        assert len(snap.confirmed_decisions) >= 2
        assert "Ingestor" in snap.current_focus
        assert len(snap.open_questions) >= 1
        assert len(snap.reference_bindings) >= 1

    @pytest.mark.asyncio
    async def test_empty_messages_returns_empty_snapshot(self) -> None:
        llm = StubLLM("")
        snap = await update_snapshot_from_messages(llm, None, [])
        assert snap.is_empty

    @pytest.mark.asyncio
    async def test_only_system_messages_returns_empty(self) -> None:
        llm = StubLLM("")
        system_msgs = [_msg("system", "You are a helpful assistant.")]
        snap = await update_snapshot_from_messages(llm, None, system_msgs)
        assert snap.is_empty

    @pytest.mark.asyncio
    async def test_llm_failure_returns_previous(self) -> None:
        llm = FailingStubLLM()
        prev = ConversationContinuitySnapshot(
            current_task="survive", current_focus="existing"
        )
        snap = await update_snapshot_from_messages(
            llm, prev, _MULTI_TURN_MSGS
        )
        assert snap is prev, "should return previous snapshot on failure"

    @pytest.mark.asyncio
    async def test_llm_failure_no_previous_returns_empty(self) -> None:
        llm = FailingStubLLM()
        snap = await update_snapshot_from_messages(
            llm, None, _MULTI_TURN_MSGS
        )
        assert snap.is_empty