"""Memory recall hit – a shard with retrieval score breakdown.

A :class:`MemoryHit` is what :meth:`HybridRetriever.recall` and
:meth:`MemoryManager.recall` return: a single :class:`MemoryShard`
together with the per-source signals that contributed to its overall
relevance score.

Keeping the breakdown around lets downstream consumers
(``InputBuilder`` / ``ContextPacker``) compute richer salience metrics
("this hit is keyword-only, low confidence" vs "high vector similarity
plus permanent flag") without re-running the search.
"""

from __future__ import annotations

from dataclasses import dataclass

from mindbot.memory.types.shard import MemoryShard


@dataclass
class MemoryHit:
    """A retrieved shard with explainable per-source scores."""

    shard: MemoryShard
    score: float = 0.0
    vector_score: float = 0.0
    fts_score: float = 0.0
    grep_score: float = 0.0
    index_score: float = 0.0
    recency_score: float = 0.0

    @property
    def shard_id(self) -> str:
        return self.shard.id

    @property
    def reason(self) -> str:
        """Human-readable explanation of which signal drove the score."""
        parts: list[tuple[str, float]] = [
            ("vector", self.vector_score),
            ("fts", self.fts_score),
            ("grep", self.grep_score),
            ("index", self.index_score),
            ("recency", self.recency_score),
        ]
        contributing = [(name, value) for name, value in parts if value > 0]
        if not contributing:
            return "no-signal"
        contributing.sort(key=lambda item: item[1], reverse=True)
        top = contributing[:2]
        return ",".join(f"{name}={value:.2f}" for name, value in top)
