"""Memory recall + pack competition – integration tests.

Verify that high-salience shards win the limited-budget tournament
inside :class:`~mindbot.context.packer.ContextPacker` while low-salience
shards get compressed or dropped.  Permanent shards should be biased
upward by the salience formula so a "permanent + low retrieval" shard
beats a "non-permanent + slightly higher retrieval" shard when scores
are close.
"""

from __future__ import annotations

from typing import Iterable

from mindbot.agent.input_builder import InputBuilder
from mindbot.config.schema import ContextConfig
from mindbot.context.manager import ContextManager
from mindbot.context.packer import ContextPacker, PackerConfig
from mindbot.memory.types import MemoryHit, MemoryShard


def _hit(
    text: str,
    *,
    shard_id: str,
    score: float,
    vector: float | None = None,
    is_permanent: bool = False,
    access_count: int = 0,
) -> MemoryHit:
    shard = MemoryShard(
        id=shard_id,
        text=text,
        is_permanent=is_permanent,
        access_count=access_count,
    )
    return MemoryHit(
        shard=shard,
        score=score,
        vector_score=vector if vector is not None else score,
    )


class FakeMemory:
    def __init__(self, hits: Iterable[MemoryHit]) -> None:
        self._hits = list(hits)

    async def recall(
        self, query: str, top_k: int = 5, cluster_type: str | None = None,
    ) -> list[MemoryHit]:
        return self._hits[:top_k]

    def append_to_short_term(self, content: str, **kw):
        return []


def _no_reserve_packer() -> ContextPacker:
    return ContextPacker(PackerConfig(response_reserve=0, min_item_tokens=4))


# ---------------------------------------------------------------------------
# 1. High-score shards survive a tight budget; low-score ones get dropped
# ---------------------------------------------------------------------------


async def test_high_score_shards_beat_low_score_under_tight_budget() -> None:
    hits = [
        _hit("HIGH-SCORE-FACT one " * 30, shard_id="hi-1", score=0.95),
        _hit("HIGH-SCORE-FACT two " * 30, shard_id="hi-2", score=0.90),
        _hit("low-score detail one " * 30, shard_id="lo-1", score=0.10),
        _hit("low-score detail two " * 30, shard_id="lo-2", score=0.05),
    ]
    memory = FakeMemory(hits)

    ctx = ContextManager(ContextConfig(max_tokens=400))
    builder = InputBuilder(
        context=ctx,
        memory=memory,  # type: ignore[arg-type]
        memory_top_k=4,
        system_prompt="sys",
        packer=_no_reserve_packer(),
    )

    msgs = await builder.build("query")
    contents = [str(m.content) for m in msgs if m.role == "system"]
    high_kept = sum(1 for c in contents if "HIGH-SCORE-FACT" in c)
    low_kept = sum(1 for c in contents if "low-score detail" in c)

    assert high_kept >= 1, "at least one high-score shard must survive"
    assert high_kept >= low_kept, (
        f"high-score shards should not lose to low-score ones "
        f"(high={high_kept}, low={low_kept})"
    )


# ---------------------------------------------------------------------------
# 2. Permanent flag boosts salience above a comparable non-permanent shard
# ---------------------------------------------------------------------------


async def test_permanent_flag_boosts_salience() -> None:
    # Both shards have similar retrieval scores but only one is permanent.
    hits = [
        _hit(
            "PERMANENT-FACT crucial detail " * 25,
            shard_id="perm-1",
            score=0.40,
            is_permanent=True,
            access_count=10,
        ),
        _hit(
            "ephemeral fact passing detail " * 25,
            shard_id="eph-1",
            score=0.45,
            is_permanent=False,
            access_count=0,
        ),
    ]
    memory = FakeMemory(hits)

    # Tight budget so the packer must pick one of the two.
    ctx = ContextManager(ContextConfig(max_tokens=260))
    builder = InputBuilder(
        context=ctx,
        memory=memory,  # type: ignore[arg-type]
        memory_top_k=2,
        system_prompt="sys",
        packer=_no_reserve_packer(),
    )

    msgs = await builder.build("query")
    contents = [str(m.content) for m in msgs if m.role == "system"]
    permanent_present = any("PERMANENT-FACT" in c for c in contents)

    assert permanent_present, (
        "permanent shards should be preferred when retrieval scores are close"
    )


# ---------------------------------------------------------------------------
# 3. ContextItem metadata exposes per-shard retrieval reason for logging
# ---------------------------------------------------------------------------


async def test_per_shard_metadata_includes_score_and_reason() -> None:
    hits = [
        _hit("Fact A", shard_id="abc12345", score=0.81, vector=0.81),
        _hit("Fact B", shard_id="def67890", score=0.42, vector=0.42),
    ]
    memory = FakeMemory(hits)

    ctx = ContextManager(ContextConfig(max_tokens=2000))
    builder = InputBuilder(
        context=ctx,
        memory=memory,  # type: ignore[arg-type]
        memory_top_k=2,
        system_prompt="sys",
        packer=_no_reserve_packer(),
    )

    # Run a full build to populate the per-turn hit cache, then inspect
    # the candidate items the packer received.
    await builder.build("query")
    items = builder._collect_items()  # type: ignore[attr-defined]
    memory_items = [i for i in items if i.source == "memory"]
    assert len(memory_items) == 2
    for item in memory_items:
        assert "score" in item.metadata
        assert "reason" in item.metadata
        assert item.metadata["score"] > 0
        assert item.name.startswith("memory:")
