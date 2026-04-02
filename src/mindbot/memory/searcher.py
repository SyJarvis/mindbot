"""Keyword searcher with hand-written relevance scoring."""

from __future__ import annotations

import re
import time

from src.mindbot.memory.storage import SQLiteStorage
from src.mindbot.memory.types import MemoryChunk


class HybridSearcher:
    """Keyword-first memory search with lightweight custom ranking."""

    def __init__(
        self,
        storage: SQLiteStorage,
    ) -> None:
        self._storage = storage

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        top_k: int = 5,
        source: str | None = None,
    ) -> list[MemoryChunk]:
        """Search memory using keyword retrieval only."""
        return self._keyword_search(query, top_k=top_k, source=source)

    # ------------------------------------------------------------------
    # Keyword search
    # ------------------------------------------------------------------

    def _keyword_search(
        self, query: str, top_k: int = 10, source: str | None = None,
    ) -> list[MemoryChunk]:
        """Hand-written keyword retrieval and ranking."""
        candidates = self._storage.search_fts(query, top_k=max(100, top_k * 10), source=source)
        if not candidates:
            return []
        q_tokens = self._tokenize(query)
        now = time.time()
        scored: list[tuple[float, MemoryChunk]] = []
        for chunk in candidates:
            text = chunk.text.lower()
            score = 0.0
            if query.lower() in text:
                score += 5.0
            chunk_tokens = self._tokenize(chunk.text)
            overlap = len(q_tokens.intersection(chunk_tokens))
            score += overlap * 1.5
            # simple recency bonus: most recent memories rank slightly higher
            hours = max((now - chunk.created_at) / 3600.0, 0.0)
            score += 1.0 / (1.0 + hours / 24.0)
            scored.append((score, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [chunk for _, chunk in scored[:top_k]]

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        tokens = [t for t in re.split(r"[^\w\u4e00-\u9fff]+", text.lower()) if t]
        return set(tokens)
