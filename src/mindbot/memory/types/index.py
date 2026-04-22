"""Shard index - lightweight index structure for JSON storage."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from mindbot.memory.types.enums import ShardSource, ShardType


@dataclass
class ShardIndex:
    """
    Shard index entry for JSON storage.

    Does NOT contain full text content - points to Markdown file.
    Designed for fast retrieval filtering and metadata access.
    """

    # Core identification
    shard_id: str                     # UUID identifier
    markdown_path: str                # Markdown file path (relative to base_path)
    chunk_id: str = ""                # Belonging chunk ID
    cluster_id: str = ""              # Belonging cluster ID

    # Quick info for filtering
    summary: str = ""                 # LLM generated summary (≤100 chars)
    keywords: list[str] = field(default_factory=list)  # Keyword tags

    # Vector binding
    vector_id: str | None = None      # Vector store ID

    # Classification
    shard_type: ShardType = ShardType.FACT
    source: ShardSource = ShardSource.USER_TOLD

    # Time
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    # Forget stats
    access_count: int = 0
    last_accessed_at: float = 0.0
    forget_score: float = 0.0
    is_archived: bool = False
    is_permanent: bool = False

    # Metadata (minimal, no full text)
    metadata: dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        """Mark as accessed, update stats."""
        self.access_count += 1
        self.last_accessed_at = time.time()

    def update_summary(self, new_summary: str, keywords: list[str] | None = None) -> None:
        """Update summary and optionally keywords."""
        self.summary = new_summary[:100]  # Cap at 100 chars
        if keywords is not None:
            self.keywords = keywords
        self.updated_at = time.time()

    @classmethod
    def create(
        cls,
        shard_id: str,
        markdown_path: str,
        summary: str = "",
        shard_type: ShardType = ShardType.FACT,
        source: ShardSource = ShardSource.USER_TOLD,
        chunk_id: str = "",
        cluster_id: str = "",
        keywords: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ShardIndex:
        """Factory method to create a new index entry."""
        now = time.time()
        return cls(
            shard_id=shard_id,
            markdown_path=markdown_path,
            summary=summary[:100],
            shard_type=shard_type,
            source=source,
            chunk_id=chunk_id,
            cluster_id=cluster_id,
            keywords=keywords or [],
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON storage."""
        return {
            "shard_id": self.shard_id,
            "markdown_path": self.markdown_path,
            "chunk_id": self.chunk_id,
            "cluster_id": self.cluster_id,
            "summary": self.summary,
            "keywords": self.keywords,
            "vector_id": self.vector_id,
            "shard_type": self.shard_type.value,
            "source": self.source.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "access_count": self.access_count,
            "last_accessed_at": self.last_accessed_at,
            "forget_score": self.forget_score,
            "is_archived": self.is_archived,
            "is_permanent": self.is_permanent,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ShardIndex:
        """Deserialize from dictionary."""
        return cls(
            shard_id=data["shard_id"],
            markdown_path=data["markdown_path"],
            chunk_id=data.get("chunk_id", ""),
            cluster_id=data.get("cluster_id", ""),
            summary=data.get("summary", ""),
            keywords=data.get("keywords", []),
            vector_id=data.get("vector_id"),
            shard_type=ShardType(data.get("shard_type", "fact")),
            source=ShardSource(data.get("source", "user_told")),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            access_count=data.get("access_count", 0),
            last_accessed_at=data.get("last_accessed_at", 0.0),
            forget_score=data.get("forget_score", 0.0),
            is_archived=data.get("is_archived", False),
            is_permanent=data.get("is_permanent", False),
            metadata=data.get("metadata", {}),
        )