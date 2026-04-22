"""Memory shard - atomic memory unit."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from mindbot.memory.types.enums import ShardSource, ShardType


@dataclass
class MemoryShard:
    """Atomic memory unit - minimum granularity, indivisible."""

    # Core content
    id: str                           # UUID identifier
    text: str                         # Memory text content
    vector_id: str | None = None      # Vector store ID (lazy binding)

    # Classification
    shard_type: ShardType = ShardType.FACT
    cluster_id: str = ""              # Belonging cluster ID
    chunk_id: str = ""                # Belonging chunk ID

    # Source attributes
    source: ShardSource = ShardSource.USER_TOLD
    confidence: float = 1.0           # Confidence level (0-1)

    # Time attributes
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    valid_from: float | None = None   # Valid start time
    valid_until: float | None = None  # Valid end time

    # Migration attributes
    is_migratable: bool = True
    origin_agent: str | None = None   # Original source agent

    # Forget attributes
    access_count: int = 0             # Access count
    last_accessed_at: float = 0.0     # Last access timestamp
    forget_score: float = 0.0         # Forget score (0-1, higher = more likely to forget)
    is_archived: bool = False
    is_permanent: bool = False        # User marked permanent

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        """Mark this shard as accessed, update stats."""
        self.access_count += 1
        self.last_accessed_at = time.time()

    def update_text(self, new_text: str) -> None:
        """Update text content."""
        self.text = new_text
        self.updated_at = time.time()

    @classmethod
    def create(
        cls,
        text: str,
        shard_type: ShardType = ShardType.FACT,
        source: ShardSource = ShardSource.USER_TOLD,
        cluster_id: str = "",
        chunk_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> MemoryShard:
        """Factory method to create a new shard."""
        import uuid
        now = time.time()
        return cls(
            id=uuid.uuid4().hex,
            text=text,
            shard_type=shard_type,
            source=source,
            cluster_id=cluster_id,
            chunk_id=chunk_id,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )