"""Memory cluster - functional domain aggregation."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from mindbot.memory.types.enums import ClusterType


# Migration priority mapping for cluster types
CLUSTER_MIGRATION_PRIORITY = {
    ClusterType.IDENTITY: 1,      # Must migrate
    ClusterType.CAPABILITY: 2,    # Must migrate
    ClusterType.RELATIONSHIP: 3,  # Optional
    ClusterType.KNOWLEDGE: 4,     # Optional
    ClusterType.EXPERIENCE: 5,    # Optional
}

# Core cluster types (must migrate)
CORE_CLUSTER_TYPES = {ClusterType.IDENTITY, ClusterType.CAPABILITY}


@dataclass
class MemoryCluster:
    """Functional memory cluster - agent capability domain."""

    # Core identification
    id: str                           # UUID identifier
    name: str                         # Cluster name
    cluster_type: ClusterType = ClusterType.KNOWLEDGE

    # Hierarchy
    profile_id: str = ""              # Belonging profile ID
    chunk_ids: list[str] = field(default_factory=list)  # Contained chunk IDs

    # Statistics
    total_shards: int = 0             # Total shard count
    total_chunks: int = 0             # Total chunk count (len(chunk_ids))

    # Migration strategy
    migration_priority: int = 3       # 1-5, lower = higher priority
    is_core: bool = False             # Whether core cluster (must migrate)

    # Time
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    # Summary
    summary: str = ""

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Set migration priority and is_core based on cluster_type."""
        self.migration_priority = CLUSTER_MIGRATION_PRIORITY.get(self.cluster_type, 3)
        self.is_core = self.cluster_type in CORE_CLUSTER_TYPES

    def add_chunk(self, chunk_id: str) -> None:
        """Add a chunk to this cluster."""
        if chunk_id not in self.chunk_ids:
            self.chunk_ids.append(chunk_id)
            self.total_chunks = len(self.chunk_ids)
            self.updated_at = time.time()

    def remove_chunk(self, chunk_id: str) -> None:
        """Remove a chunk from this cluster."""
        if chunk_id in self.chunk_ids:
            self.chunk_ids.remove(chunk_id)
            self.total_chunks = len(self.chunk_ids)
            self.updated_at = time.time()

    def update_shard_count(self, count: int) -> None:
        """Update total shard count."""
        self.total_shards = count
        self.updated_at = time.time()

    @classmethod
    def create(
        cls,
        name: str,
        cluster_type: ClusterType,
        profile_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryCluster:
        """Factory method to create a new cluster."""
        import uuid
        now = time.time()
        return cls(
            id=uuid.uuid4().hex,
            name=name,
            cluster_type=cluster_type,
            profile_id=profile_id,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )