"""Memory profile - agent identity definition."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MemoryProfile:
    """Agent complete identity definition - top-level encapsulation."""

    # Core identification
    agent_id: str                     # Unique agent identifier
    agent_name: str                   # Agent display name
    profile_version: str = "1.0"      # Profile schema version

    # Identity core (LLM generated)
    identity_definition: str = ""     # "Who am I" description
    personality_traits: dict[str, float] = field(default_factory=dict)  # {trait: score}
    core_values: list[str] = field(default_factory=list)
    communication_style: str = ""

    # Cluster composition
    cluster_ids: list[str] = field(default_factory=list)

    # Statistics
    total_shards: int = 0
    total_chunks: int = 0
    total_clusters: int = 0

    # Migration metadata
    compatibility_version: str = "mindbot-v1.0"  # Schema compatibility
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_migration_at: float | None = None
    migration_count: int = 0
    origin_agent: str | None = None  # Clone source agent

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_cluster(self, cluster_id: str) -> None:
        """Add a cluster to this profile."""
        if cluster_id not in self.cluster_ids:
            self.cluster_ids.append(cluster_id)
            self.total_clusters = len(self.cluster_ids)
            self.updated_at = time.time()

    def remove_cluster(self, cluster_id: str) -> None:
        """Remove a cluster from this profile."""
        if cluster_id in self.cluster_ids:
            self.cluster_ids.remove(cluster_id)
            self.total_clusters = len(self.cluster_ids)
            self.updated_at = time.time()

    def update_stats(self, shards: int, chunks: int) -> None:
        """Update statistics."""
        self.total_shards = shards
        self.total_chunks = chunks
        self.updated_at = time.time()

    def get_identity_summary(self) -> str:
        """Get a summary of agent identity."""
        parts = []
        if self.agent_name:
            parts.append(f"Name: {self.agent_name}")
        if self.identity_definition:
            parts.append(f"Definition: {self.identity_definition}")
        if self.personality_traits:
            traits = ", ".join(f"{k}:{v:.1f}" for k, v in self.personality_traits.items())
            parts.append(f"Traits: {traits}")
        if self.core_values:
            parts.append(f"Values: {', '.join(self.core_values)}")
        return "\n".join(parts)

    @classmethod
    def create(
        cls,
        agent_id: str,
        agent_name: str,
        identity_definition: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> MemoryProfile:
        """Factory method to create a new profile."""
        now = time.time()
        return cls(
            agent_id=agent_id,
            agent_name=agent_name,
            identity_definition=identity_definition,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )