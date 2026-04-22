"""Memory chunk - thematic aggregation unit."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from mindbot.memory.types.enums import ChunkType


@dataclass
class MemoryChunk:
    """Thematic memory chunk - collection of related memory shards."""

    # Core identification
    id: str                           # UUID identifier
    name: str                         # Chunk name, e.g., "Python_Programming"
    description: str = ""             # Chunk description

    # Hierarchy
    cluster_id: str = ""              # Belonging cluster ID
    shard_ids: list[str] = field(default_factory=list)  # Contained shard IDs

    # Classification
    chunk_type: ChunkType = ChunkType.KNOWLEDGE

    # Statistics
    total_access: int = 0             # Total access count of all shards
    importance_score: float = 0.5     # Chunk importance (0-1)

    # Migration
    is_exportable: bool = True

    # Time
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    # Summary (optional LLM generated)
    summary: str = ""

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_shard(self, shard_id: str) -> None:
        """Add a shard to this chunk."""
        if shard_id not in self.shard_ids:
            self.shard_ids.append(shard_id)
            self.updated_at = time.time()

    def remove_shard(self, shard_id: str) -> None:
        """Remove a shard from this chunk."""
        if shard_id in self.shard_ids:
            self.shard_ids.remove(shard_id)
            self.updated_at = time.time()

    @property
    def shard_count(self) -> int:
        """Number of shards in this chunk."""
        return len(self.shard_ids)

    @classmethod
    def create(
        cls,
        name: str,
        cluster_id: str,
        chunk_type: ChunkType = ChunkType.KNOWLEDGE,
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> MemoryChunk:
        """Factory method to create a new chunk."""
        import uuid
        now = time.time()
        return cls(
            id=uuid.uuid4().hex,
            name=name,
            cluster_id=cluster_id,
            chunk_type=chunk_type,
            description=description,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )