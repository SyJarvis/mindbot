"""Tests for :class:`HybridRetriever.recall` – semantic + keyword + recency.

These tests stub every storage layer so the retriever's five signals
can be exercised independently:

* vector (embedder + LanceDB cosine)
* FTS (LanceDB full-text)
* grep (Markdown content store)
* index (JSON index store keyword summary)
* recency (time-decayed bonus)

Each test sets up exactly one signal and asserts the corresponding
field on :class:`~mindbot.memory.types.MemoryHit` carries a positive
value, while :attr:`MemoryHit.reason` describes the dominant source.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from mindbot.providers.embeddings.base import Embedder
from mindbot.memory.retrieval.searcher import HybridRetriever
from mindbot.memory.storage.vector_store import SearchResult, VectorStore
from mindbot.memory.types import ShardIndex, ShardSource, ShardType


class StubVectorStore(VectorStore):
    """In-memory stub returning canned vector / FTS results."""

    def __init__(
        self,
        vector_results: list[SearchResult] | None = None,
        fts_results: list[SearchResult] | None = None,
    ) -> None:
        self.vector_results = vector_results or []
        self.fts_results = fts_results or []

    def insert(self, shard_id: str, vector: list[float], metadata: dict | None = None) -> None:
        pass

    def insert_batch(self, items: list[tuple[str, list[float], dict | None]]) -> None:
        pass

    def search(
        self,
        vector: list[float],
        top_k: int = 10,
        filter_expr: str | None = None,
    ) -> list[SearchResult]:
        return list(self.vector_results)

    def search_by_text(
        self,
        query: str,
        top_k: int = 10,
        filter_expr: str | None = None,
    ) -> list[SearchResult]:
        return list(self.fts_results)

    def delete(self, shard_id: str) -> None:
        pass

    def update(self, shard_id: str, new_vector: list[float], metadata: dict | None = None) -> None:
        pass

    def get_vector(self, shard_id: str) -> list[float] | None:
        return None

    def count(self) -> int:
        return 0


class StubIndexStore:
    """Index store stub holding a few :class:`ShardIndex` objects."""

    def __init__(self, indices: dict[str, ShardIndex]) -> None:
        self._indices = indices

    def get_shard_index(self, shard_id: str) -> ShardIndex | None:
        return self._indices.get(shard_id)

    def update_shard_index(self, shard_id: str, index: ShardIndex) -> None:
        self._indices[shard_id] = index

    def search_indices_by_keywords(
        self, keywords: list[str], limit: int = 50,
    ) -> list[ShardIndex]:
        if not keywords:
            return []
        hits: list[ShardIndex] = []
        for index in self._indices.values():
            haystack = (index.summary + " " + " ".join(index.keywords)).lower()
            for kw in keywords:
                if kw and kw.lower() in haystack:
                    hits.append(index)
                    break
            if len(hits) >= limit:
                break
        return hits


class StubContentStore:
    """Content store stub backed by an in-memory dict of shard text."""

    def __init__(self, contents: dict[str, str]) -> None:
        self._contents = contents

    def read_shard(self, shard_id: str) -> str:
        return self._contents.get(shard_id, "")

    def search_by_keyword(self, query: str, limit: int = 50) -> list[str]:
        q = query.lower()
        if not q:
            return []
        return [sid for sid, text in self._contents.items() if q in text.lower()][:limit]


class StubEmbedder(Embedder):
    async def encode(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0]

    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]

    @property
    def dimension(self) -> int:
        return 3


def _index(shard_id: str, *, summary: str = "", keywords: list[str] | None = None,
           created_at: float | None = None) -> ShardIndex:
    return ShardIndex(
        shard_id=shard_id,
        markdown_path=f"{shard_id}.md",
        summary=summary,
        shard_type=ShardType.FACT,
        source=ShardSource.USER_TOLD,
        chunk_id="chunk",
        cluster_id="cluster",
        keywords=keywords or [],
        created_at=created_at if created_at is not None else time.time(),
        updated_at=time.time(),
    )


@pytest.fixture()
def stores_with_python_shard():
    """Three stores wired with a single 'python' shard for keyword paths."""
    contents = {"shard-1": "User likes the Python programming language"}
    indices = {
        "shard-1": _index(
            "shard-1",
            summary="Discussion about Python preferences",
            keywords=["python"],
            created_at=time.time(),
        )
    }
    return StubVectorStore(), StubIndexStore(indices), StubContentStore(contents)


# ---------------------------------------------------------------------------
# Per-signal tests
# ---------------------------------------------------------------------------


async def test_vector_signal_contributes(stores_with_python_shard: Any) -> None:
    vstore, istore, cstore = stores_with_python_shard
    vstore.vector_results = [SearchResult(shard_id="shard-1", score=0.9, distance=0.1)]
    retriever = HybridRetriever(
        vstore, istore, cstore,
        embedder=StubEmbedder(),
        vector_weight=1.0, keyword_weight=0.0, recency_weight=0.0,
    )

    hits = await retriever.recall("python", top_k=3)

    assert len(hits) == 1
    assert hits[0].vector_score > 0
    assert hits[0].fts_score == 0
    assert "vector" in hits[0].reason


async def test_fts_signal_contributes(stores_with_python_shard: Any) -> None:
    vstore, istore, cstore = stores_with_python_shard
    vstore.fts_results = [SearchResult(shard_id="shard-1", score=0.7, distance=0.3)]
    retriever = HybridRetriever(
        vstore, istore, cstore,
        embedder=None,
        vector_weight=0.0, keyword_weight=1.0, recency_weight=0.0,
    )

    hits = await retriever.recall("python", top_k=3)

    assert len(hits) == 1
    assert hits[0].fts_score >= 0.7
    assert "fts" in hits[0].reason


async def test_grep_signal_contributes(stores_with_python_shard: Any) -> None:
    vstore, istore, cstore = stores_with_python_shard
    retriever = HybridRetriever(
        vstore, istore, cstore,
        embedder=None,
        vector_weight=0.0, keyword_weight=1.0, recency_weight=0.0,
    )

    hits = await retriever.recall("python", top_k=3)

    assert len(hits) == 1
    assert hits[0].grep_score > 0
    assert "grep" in hits[0].reason


async def test_index_keyword_signal_contributes() -> None:
    contents = {"shard-2": "completely unrelated payload"}
    indices = {
        "shard-2": _index(
            "shard-2",
            summary="Notes about Rust borrow checker",
            keywords=["rust"],
            created_at=time.time(),
        )
    }
    retriever = HybridRetriever(
        StubVectorStore(), StubIndexStore(indices), StubContentStore(contents),
        embedder=None,
        vector_weight=0.0, keyword_weight=1.0, recency_weight=0.0,
    )

    hits = await retriever.recall("rust", top_k=3)

    assert len(hits) == 1
    assert hits[0].index_score > 0
    assert "index" in hits[0].reason


async def test_recency_signal_contributes(stores_with_python_shard: Any) -> None:
    vstore, istore, cstore = stores_with_python_shard
    # Force only the recency path to score: keyword weight zero so grep/index don't add to .score.
    retriever = HybridRetriever(
        vstore, istore, cstore,
        embedder=None,
        vector_weight=0.0, keyword_weight=0.0, recency_weight=1.0,
    )

    hits = await retriever.recall("python", top_k=3)

    assert len(hits) == 1
    assert hits[0].recency_score > 0


async def test_reason_combines_top_two_sources(stores_with_python_shard: Any) -> None:
    vstore, istore, cstore = stores_with_python_shard
    vstore.vector_results = [SearchResult(shard_id="shard-1", score=0.95, distance=0.05)]
    vstore.fts_results = [SearchResult(shard_id="shard-1", score=0.4, distance=0.6)]
    retriever = HybridRetriever(
        vstore, istore, cstore,
        embedder=StubEmbedder(),
        vector_weight=0.5, keyword_weight=0.35, recency_weight=0.15,
    )

    hits = await retriever.recall("python", top_k=3)

    assert len(hits) == 1
    reason = hits[0].reason
    # Both vector and fts should be picked up; reason lists at most two.
    assert "vector" in reason
    assert "," in reason  # multiple sources separated


async def test_recall_runs_without_embedder(stores_with_python_shard: Any) -> None:
    """No embedder → vector path skipped, other signals still fire."""
    vstore, istore, cstore = stores_with_python_shard
    retriever = HybridRetriever(vstore, istore, cstore, embedder=None)

    hits = await retriever.recall("python", top_k=3)

    assert len(hits) == 1
    assert hits[0].vector_score == 0.0
    assert hits[0].score > 0  # grep + index + recency still combine


async def test_recall_returns_empty_list_when_no_match() -> None:
    retriever = HybridRetriever(
        StubVectorStore(),
        StubIndexStore({}),
        StubContentStore({}),
        embedder=None,
    )

    hits = await retriever.recall("anything", top_k=3)

    assert hits == []
