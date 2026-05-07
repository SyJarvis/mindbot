"""Cognitive-workspace integration tests for :class:`InputBuilder`.

These tests drive the full ``InputBuilder.build()`` pipeline and verify
that the new pack-based assembly behaves as designed:

* Empty blocks (skills/memory/intent) yield their share of the budget
  to other content rather than locking it away.
* Memory shards keep a useful subset when over budget, instead of
  being dropped wholesale.
* Conversation history compresses dynamically against whatever budget
  is left.
* Long user input never permanently corrupts the system identity that
  is held in :class:`ContextManager`.

Post Memory Recall refactor :class:`InputBuilder.build` is async, the
memory pipeline returns :class:`~mindbot.memory.types.MemoryHit`
objects, and each shard is promoted to its own :class:`ContextItem`.
"""

from __future__ import annotations

from mindbot.agent.input_builder import InputBuilder
from mindbot.config.schema import ContextConfig
from mindbot.context.manager import ContextManager
from mindbot.context.models import Message
from mindbot.context.packer import ContextPacker, PackerConfig
from mindbot.memory.types import MemoryHit, MemoryShard


def _shard(text: str, *, shard_id: str = "s", **kwargs) -> MemoryShard:
    return MemoryShard(id=shard_id, text=text, **kwargs)


def _hit(text: str, *, shard_id: str = "s", score: float = 0.5, **shard_kw) -> MemoryHit:
    return MemoryHit(
        shard=_shard(text, shard_id=shard_id, **shard_kw),
        score=score,
        vector_score=score,
    )


class FakeMemory:
    def __init__(self, hits: list[MemoryHit]) -> None:
        self._hits = hits

    async def recall(
        self, query: str, top_k: int = 5, cluster_type: str | None = None,
    ) -> list[MemoryHit]:
        return self._hits[:top_k]

    def append_to_short_term(self, content: str, **kw):
        return []


def _no_reserve_packer() -> ContextPacker:
    return ContextPacker(PackerConfig(response_reserve=0, min_item_tokens=4))


# ---------------------------------------------------------------------------
# 1. Empty blocks yield budget
# ---------------------------------------------------------------------------


async def test_empty_skills_and_memory_let_conversation_use_full_budget() -> None:
    ctx = ContextManager(ContextConfig(max_tokens=2000))
    builder = InputBuilder(
        context=ctx,
        system_prompt="You are helpful.",
        packer=_no_reserve_packer(),
    )

    for i in range(20):
        ctx.add_conversation_message("user", f"message {i} " * 10)
        ctx.add_conversation_message("assistant", f"reply {i} " * 10)

    msgs = await builder.build("ping")
    user_msgs = [m for m in msgs if m.role == "user" and "message" in str(m.content)]
    assistant_msgs = [m for m in msgs if m.role == "assistant"]

    assert len(user_msgs) + len(assistant_msgs) >= 30


# ---------------------------------------------------------------------------
# 2. Memory shards keep a useful subset
# ---------------------------------------------------------------------------


async def test_memory_shards_compressed_to_fit_not_dropped_wholesale() -> None:
    """Per-shard items: tight budget retains the highest-scoring subset."""
    hits = [
        _hit(
            f"fact {i} important detail " * 10,
            shard_id=f"s{i:02d}",
            score=1.0 - i * 0.05,
        )
        for i in range(15)
    ]
    memory = FakeMemory(hits)

    ctx = ContextManager(ContextConfig(max_tokens=600))
    builder = InputBuilder(
        context=ctx,
        memory=memory,  # type: ignore[arg-type]
        memory_top_k=15,
        system_prompt="sys",
        packer=ContextPacker(PackerConfig(response_reserve=0, min_item_tokens=4)),
    )

    msgs = await builder.build("query")
    memory_msgs = [
        m for m in msgs
        if m.role == "system"
        and isinstance(m.content, str)
        and m.content.startswith("- fact ")
    ]

    assert len(memory_msgs) >= 1, "at least one shard should survive"
    assert len(memory_msgs) < 15, "tight budget must drop some shards"


async def test_memory_block_never_dropped_silently_at_state_level() -> None:
    """ContextManager should not silently drop memory messages that
    exceed the soft block budget – the packer needs to see all shards."""
    ctx = ContextManager(ContextConfig(max_tokens=500))

    big_msg = Message(role="system", content=("memory line " * 200))
    ctx.set_memory_messages([big_msg])

    assert ctx.get_block("memory").messages == [big_msg]


# ---------------------------------------------------------------------------
# 3. Long user input does not corrupt system identity
# ---------------------------------------------------------------------------


async def test_long_user_input_does_not_truncate_stored_system_identity() -> None:
    ctx = ContextManager(ContextConfig(max_tokens=500))
    builder = InputBuilder(
        context=ctx,
        system_prompt="You are an assistant. " * 30,
        packer=_no_reserve_packer(),
    )
    original_sys = ctx.get_block_messages("system_identity")[0].content

    huge_user = "tell me " * 5000
    await builder.build(huge_user)

    after_sys = ctx.get_block_messages("system_identity")[0].content
    assert after_sys == original_sys, (
        "system_identity must remain pristine in ContextManager; "
        "any truncation should happen only in the packed prompt"
    )


def test_long_user_input_stored_verbatim() -> None:
    ctx = ContextManager(ContextConfig(max_tokens=500))
    huge_user = "x " * 5000
    user_msg = Message(role="user", content=huge_user)
    ctx.set_user_input(user_msg)

    assert ctx.get_block_messages("user_input")[0].content == huge_user


# ---------------------------------------------------------------------------
# 4. Conversation compresses against actual leftover budget
# ---------------------------------------------------------------------------


async def test_conversation_compresses_to_fit_remaining_budget() -> None:
    ctx = ContextManager(ContextConfig(max_tokens=600))
    builder = InputBuilder(
        context=ctx,
        system_prompt="sys",
        packer=_no_reserve_packer(),
    )

    for i in range(50):
        ctx.add_conversation_message("user", f"q{i} hello world this is text " * 4)
        ctx.add_conversation_message("assistant", f"a{i} reply with words " * 4)

    msgs = await builder.build("now")

    total_tokens = sum(m.token_count or 1 for m in msgs)
    assert total_tokens <= 600

    contents = [str(m.content) for m in msgs]
    assert any("a49" in c for c in contents) or any("q49" in c for c in contents)


# ---------------------------------------------------------------------------
# 5. Required items always present
# ---------------------------------------------------------------------------


async def test_system_and_user_input_always_present() -> None:
    ctx = ContextManager(ContextConfig(max_tokens=200))
    builder = InputBuilder(
        context=ctx,
        system_prompt="sys core",
        packer=_no_reserve_packer(),
    )
    msgs = await builder.build("hi")

    assert msgs[0].role == "system"
    assert msgs[-1].role == "user"
    assert msgs[-1].content == "hi"


# ---------------------------------------------------------------------------
# 6. Response reserve respected
# ---------------------------------------------------------------------------


async def test_response_reserve_subtracts_from_budget() -> None:
    ctx = ContextManager(ContextConfig(max_tokens=2000))
    packer = ContextPacker(PackerConfig(response_reserve=1500, min_item_tokens=4))
    builder = InputBuilder(
        context=ctx,
        system_prompt="sys",
        packer=packer,
    )
    for i in range(40):
        ctx.add_conversation_message("user", f"line {i} " * 15)

    msgs = await builder.build("now")
    total = sum(m.token_count or 1 for m in msgs)
    assert total <= 500
