"""Hybrid retriever - combines vector search with keyword/FTS search."""

from __future__ import annotations

import time

from mindbot.memory.embedder.base import Embedder
from mindbot.memory.storage.content_store import MarkdownContentStore
from mindbot.memory.storage.index_store import JSONIndexStore
from mindbot.memory.storage.vector_store import VectorStore
from mindbot.memory.types import MemoryShard
from mindbot.utils import get_logger

logger = get_logger("memory.hybrid_retriever")


class HybridRetriever:
    """Hybrid retrieval: vector similarity + keyword FTS + recency scoring."""

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

    async def search(
        self,
        query: str,
        top_k: int = 5,
        cluster_type: str | None = None,
        chunk_type: str | None = None,
    ) -> list[MemoryShard]:
        """
        Hybrid search combining vector, keyword, and recency signals.

        Returns full MemoryShard objects with text loaded from Markdown.
        """
        # Build filter expression
        filter_expr = None
        if cluster_type:
            filter_expr = f'cluster_id = "{cluster_type}"'

        # Collect candidates from all sources
        candidates: dict[str, float] = {}  # shard_id → combined score

        # 1. Vector search (if embedder available)
        if self._embedder:
            try:
                vector = await self._embedder.encode(query)
                vector_results = self._vector_store.search(
                    vector, top_k=top_k * 3, filter_expr=filter_expr,
                )
                for result in vector_results:
                    score = result.score * self._vector_weight
                    candidates[result.shard_id] = candidates.get(result.shard_id, 0.0) + score
            except Exception as e:
                logger.debug(f"Vector search failed: {e}")

        # 2. FTS keyword search (via LanceDB)
        try:
            fts_results = self._vector_store.search_by_text(
                query, top_k=top_k * 3, filter_expr=filter_expr,
            )
            for result in fts_results:
                score = max(result.score, 0.1) * self._keyword_weight
                candidates[result.shard_id] = candidates.get(result.shard_id, 0.0) + score
        except Exception as e:
            logger.debug(f"FTS search failed: {e}")

        # 3. Markdown keyword search (fallback / supplement)
        md_matches = self._content_store.search_by_keyword(query, limit=top_k * 3)
        for shard_id in md_matches:
            score = 0.3 * self._keyword_weight  # Lower weight for basic grep
            candidates[shard_id] = candidates.get(shard_id, 0.0) + score

        # 4. JSON index summary match
        indices = self._index_store.search_indices_by_keywords(
            query.split(), limit=top_k * 3,
        )
        for idx in indices:
            score = 0.2 * self._keyword_weight
            candidates[idx.shard_id] = candidates.get(idx.shard_id, 0.0) + score

        # 5. Add recency bonus
        now = time.time()
        for shard_id in list(candidates.keys()):
            index = self._index_store.get_shard_index(shard_id)
            if index:
                hours = max((now - index.created_at) / 3600.0, 0.0)
                recency = 1.0 / (1.0 + hours / 24.0)
                candidates[shard_id] += recency * self._recency_weight

        # Sort by combined score
        sorted_ids = sorted(candidates.keys(), key=lambda x: candidates[x], reverse=True)

        # Load full content and build MemoryShard objects
        shards = []
        for shard_id in sorted_ids[:top_k]:
            shard = self._load_shard(shard_id)
            if shard:
                shards.append(shard)

        logger.debug(f"Hybrid search '{query[:30]}' returned {len(shards)} shards")
        return shards

    def search_sync(
        self,
        query: str,
        top_k: int = 5,
    ) -> list[MemoryShard]:
        """Synchronous hybrid search (keyword-only, no vector)."""
        candidates: dict[str, float] = {}

        # FTS keyword search
        try:
            fts_results = self._vector_store.search_by_text(query, top_k=top_k * 3)
            for result in fts_results:
                score = max(result.score, 0.1)
                candidates[result.shard_id] = candidates.get(result.shard_id, 0.0) + score
        except Exception:
            pass

        # Markdown keyword search
        md_matches = self._content_store.search_by_keyword(query, limit=top_k * 3)
        for shard_id in md_matches:
            candidates[shard_id] = candidates.get(shard_id, 0.0) + 0.5

        # JSON index summary match
        indices = self._index_store.search_indices_by_keywords(query.split(), limit=top_k * 3)
        for idx in indices:
            candidates[idx.shard_id] = candidates.get(idx.shard_id, 0.0) + 0.3

        # Recency bonus
        now = time.time()
        for shard_id in list(candidates.keys()):
            index = self._index_store.get_shard_index(shard_id)
            if index:
                hours = max((now - index.created_at) / 3600.0, 0.0)
                recency = 1.0 / (1.0 + hours / 24.0)
                candidates[shard_id] += recency * 0.2

        # Sort and load
        sorted_ids = sorted(candidates.keys(), key=lambda x: candidates[x], reverse=True)
        shards = []
        for shard_id in sorted_ids[:top_k]:
            shard = self._load_shard(shard_id)
            if shard:
                shards.append(shard)

        return shards

    def _load_shard(self, shard_id: str) -> MemoryShard | None:
        """Load a full MemoryShard from index + content stores."""
        index = self._index_store.get_shard_index(shard_id)
        if not index:
            return None

        content = self._content_store.read_shard(shard_id)
        if not content:
            return None

        # Update access stats
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
