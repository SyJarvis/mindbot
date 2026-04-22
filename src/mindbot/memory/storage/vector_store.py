"""Vector store abstraction and search result types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SearchResult:
    """A single search result from vector store."""

    shard_id: str
    score: float          # Similarity score (higher = more similar)
    distance: float       # Distance metric (lower = more similar)


class VectorStore(ABC):
    """Abstract vector store interface."""

    @abstractmethod
    def insert(self, shard_id: str, vector: list[float], metadata: dict | None = None) -> None:
        """Insert a vector with optional metadata."""

    @abstractmethod
    def insert_batch(self, items: list[tuple[str, list[float], dict | None]]) -> None:
        """Insert multiple vectors at once."""

    @abstractmethod
    def search(
        self,
        vector: list[float],
        top_k: int = 10,
        filter_expr: str | None = None,
    ) -> list[SearchResult]:
        """Search by vector similarity."""

    @abstractmethod
    def search_by_text(
        self,
        query: str,
        top_k: int = 10,
        filter_expr: str | None = None,
    ) -> list[SearchResult]:
        """Full-text search by query string."""

    @abstractmethod
    def delete(self, shard_id: str) -> None:
        """Delete a vector by shard ID."""

    @abstractmethod
    def update(self, shard_id: str, new_vector: list[float], metadata: dict | None = None) -> None:
        """Update a vector."""

    @abstractmethod
    def get_vector(self, shard_id: str) -> list[float] | None:
        """Get vector by shard ID."""

    @abstractmethod
    def count(self) -> int:
        """Total number of vectors."""
