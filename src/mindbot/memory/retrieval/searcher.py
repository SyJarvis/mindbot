"""Hybrid retriever – semantic recall over MindBot's memory store.

The retriever combines five signals to score every candidate shard:

1. Vector similarity (LanceDB cosine), seeded from a query embedding.
2. Full-text search (LanceDB FTS over the indexed text column).
3. Markdown grep over the on-disk content store.
4. JSON-index keyword match (against ``ShardIndex.summary`` / keywords).
5. Recency bonus that decays with shard age.

Each signal contributes to a per-shard :class:`MemoryHit` so callers
(``InputBuilder``, ``ContextPacker``) can reason about *why* a shard
was retrieved – not just its overall score.

The previous synchronous, keyword-only ``search_sync`` entrypoint was
intentionally removed when the cognitive workspace migration moved
``InputBuilder`` to async; ``recall`` is now the single entrypoint.
"""

from __future__ import annotations

import time

from mindbot.providers.embeddings.base import Embedder
from mindbot.memory.storage.content_store import MarkdownContentStore
from mindbot.memory.storage.index_store import JSONIndexStore
from mindbot.memory.storage.vector_store import VectorStore
from mindbot.memory.types import MemoryHit, MemoryShard
from mindbot.logging import logger


class HybridRetriever:
    """Hybrid recall: vector similarity + keyword/FTS + recency scoring."""

    def __init__(
        self,
        vector_store: VectorStore,
        index_store: JSONIndexStore,
        content_store: MarkdownContentStore,
        embedder: Embedder | None = None,
        vector_weight: float = 0.5,
        keyword_weight: float = 0.35,
        recency_weight: float = 0.15,
    ) -> None:
        self._vector_store = vector_store
        self._index_store = index_store
        self._content_store = content_store
        self._embedder = embedder
        self._vector_weight = vector_weight
        self._keyword_weight = keyword_weight
        self._recency_weight = recency_weight

    async def recall(
        self,
        query: str,
        top_k: int = 5,
        cluster_type: str | None = None,
    ) -> list[MemoryHit]:
        """Hybrid recall returning explainable :class:`MemoryHit` objects.

        Each hit carries the contribution of every signal so downstream
        salience scoring can weigh, e.g., "vector + recency" vs
        "keyword grep only".
        """
        filter_expr = None
        if cluster_type:
            filter_expr = f'cluster_id = "{cluster_type}"'

        hits: dict[str, MemoryHit] = {}

        def _bucket(shard_id: str) -> MemoryHit:
            existing = hits.get(shard_id)
            if existing is None:
                existing = MemoryHit(shard=MemoryShard(id=shard_id, text=""))
                hits[shard_id] = existing
            return existing

        # 1. Vector search (skipped when embedder is unavailable).
        if self._embedder:
            try:
                vector = await self._embedder.encode(query)
                vector_results = self._vector_store.search(
                    vector, top_k=top_k * 3, filter_expr=filter_expr,
                )
                for result in vector_results:
                    hit = _bucket(result.shard_id)
                    score = float(result.score)
                    if score > hit.vector_score:
                        hit.score += (score - hit.vector_score) * self._vector_weight
                        hit.vector_score = score
            except Exception as exc:
                logger.debug("Vector recall failed: {}", exc)

        # 2. FTS keyword search (LanceDB built-in).
        try:
            fts_results = self._vector_store.search_by_text(
                query, top_k=top_k * 3, filter_expr=filter_expr,
            )
            for result in fts_results:
                hit = _bucket(result.shard_id)
                fts = max(float(result.score), 0.1)
                if fts > hit.fts_score:
                    hit.score += (fts - hit.fts_score) * self._keyword_weight
                    hit.fts_score = fts
        except Exception as exc:
            logger.debug("FTS recall failed: {}", exc)

        # 3. Markdown grep fallback.
        md_matches = self._content_store.search_by_keyword(query, limit=top_k * 3)
        grep_value = 0.3
        for shard_id in md_matches:
            hit = _bucket(shard_id)
            if hit.grep_score < grep_value:
                hit.score += (grep_value - hit.grep_score) * self._keyword_weight
                hit.grep_score = grep_value

        # 4. JSON-index keyword summary match.
        indices = self._index_store.search_indices_by_keywords(
            query.split(), limit=top_k * 3,
        )
        index_value = 0.2
        for idx in indices:
            hit = _bucket(idx.shard_id)
            if hit.index_score < index_value:
                hit.score += (index_value - hit.index_score) * self._keyword_weight
                hit.index_score = index_value

        # 5. Recency bonus.
        now = time.time()
        for shard_id, hit in hits.items():
            index = self._index_store.get_shard_index(shard_id)
            if index is None:
                continue
            hours = max((now - index.created_at) / 3600.0, 0.0)
            recency = 1.0 / (1.0 + hours / 24.0)
            hit.recency_score = recency
            hit.score += recency * self._recency_weight

        # Sort by combined score, take top_k, hydrate full shard text.
        sorted_ids = sorted(hits.keys(), key=lambda sid: hits[sid].score, reverse=True)
        result: list[MemoryHit] = []
        for shard_id in sorted_ids[:top_k]:
            hit = hits[shard_id]
            shard = self._load_shard(shard_id)
            if shard is None:
                continue
            hit.shard = shard
            result.append(hit)

        logger.debug(
            "memory.recall query={} hits={} top={}",
            query[:30],
            len(result),
            ",".join(f"{h.shard_id[:8]}:{h.score:.2f}" for h in result[:3]),
        )
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_shard(self, shard_id: str) -> MemoryShard | None:
        """Hydrate a full :class:`MemoryShard` from index + content stores."""
        index = self._index_store.get_shard_index(shard_id)
        if not index:
            return None

        content = self._content_store.read_shard(shard_id)
        if not content:
            return None

        index.touch()
        self._index_store.update_shard_index(shard_id, index)

        return MemoryShard(
            id=shard_id,
            text=content,
            shard_type=index.shard_type,
            source=index.source,
            cluster_id=index.cluster_id,
            chunk_id=index.chunk_id,
            created_at=index.created_at,
            updated_at=index.updated_at,
            access_count=index.access_count,
            forget_score=index.forget_score,
            is_archived=index.is_archived,
            is_permanent=index.is_permanent,
            metadata=index.metadata,
        )
