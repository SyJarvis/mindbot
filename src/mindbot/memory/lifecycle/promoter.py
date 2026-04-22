"""Memory promoter - elevate short-term memories to long-term."""

from __future__ import annotations

import time
from typing import Any

from mindbot.memory.storage.content_store import MarkdownContentStore
from mindbot.memory.storage.index_store import JSONIndexStore
from mindbot.memory.types import ClusterType, MemoryCluster, MemoryChunk, ShardIndex, ShardType
from mindbot.utils import get_logger

logger = get_logger("memory.promoter")


class MemoryPromoter:
    """
    Promote memories from short-term to long-term storage.

    Criteria for promotion:
    1. High access count (frequently referenced)
    2. High importance score (explicitly marked or inferred)
    3. Age threshold (memories that survived initial decay period)
    4. User explicitly marked as important
    """

    def __init__(
        self,
        index_store: JSONIndexStore,
        content_store: MarkdownContentStore,
        promotion_threshold: float = 0.7,
        min_access_count: int = 3,
        min_age_hours: float = 24.0,
    ) -> None:
        self._index_store = index_store
        self._content_store = content_store
        self._promotion_threshold = promotion_threshold
        self._min_access_count = min_access_count
        self._min_age_hours = min_age_hours

    def compute_promotion_score(self, index: ShardIndex) -> float:
        """Calculate promotion score (0-1, higher = should promote)."""
        score = 0.0

        # 1. Access frequency (high access → promote)
        if index.access_count >= self._min_access_count:
            access_bonus = min(index.access_count / 10.0, 0.4)
            score += access_bonus

        # 2. Age (survived initial period → more stable)
        age_hours = (time.time() - index.created_at) / 3600
        if age_hours >= self._min_age_hours:
            age_bonus = min(age_hours / (self._min_age_hours * 7), 0.3)
            score += age_bonus

        # 3. Importance score (if set)
        importance = index.metadata.get("importance_score", 0.5)
        score += importance * 0.2

        # 4. Permanent marking
        if index.is_permanent:
            score += 0.3

        # 5. Source type (user-told facts are more valuable)
        if index.source.value == "user_told":
            score += 0.1

        return min(score, 1.0)

    def run_promotion_cycle(self) -> dict[str, Any]:
        """
        Scan all memories and promote candidates.

        Returns: {"promoted": [shard_ids], "candidates": [shard_ids]}
        """
        indices = self._index_store.load_all_indices()

        promoted = []
        candidates = []

        for shard_id, index in indices.items():
            # Skip already archived or permanent
            if index.is_archived:
                continue

            score = self.compute_promotion_score(index)

            if score >= self._promotion_threshold:
                candidates.append((shard_id, score))

        # Sort by score, promote top candidates
        candidates.sort(key=lambda x: x[1], reverse=True)

        for shard_id, score in candidates[:50]:  # Limit promotions per cycle
            if self._promote_shard(shard_id):
                promoted.append(shard_id)

        logger.info(f"Promotion cycle: {len(promoted)} memories promoted")

        return {
            "promoted": promoted,
            "candidates": [c[0] for c in candidates],
            "executed_at": time.time(),
        }

    def _promote_shard(self, shard_id: str) -> bool:
        """Move a shard to long-term cluster."""
        index = self._index_store.get_shard_index(shard_id)
        if not index:
            return False

        # Find target cluster (KNOWLEDGE for facts, IDENTITY for preferences)
        target_cluster_type = self._get_target_cluster_type(index)
        target_cluster = self._index_store.get_cluster_by_type(target_cluster_type)

        if not target_cluster:
            # Create target cluster
            profile = self._index_store.get_active_profile()
            if profile:
                target_cluster = MemoryCluster.create(
                    name=target_cluster_type.value,
                    cluster_type=target_cluster_type,
                    profile_id=profile.agent_id,
                )
                self._index_store.save_cluster(target_cluster)
                profile.add_cluster(target_cluster.id)
                self._index_store.save_profile(profile)

        if not target_cluster:
            logger.warning(f"Cannot promote {shard_id}: no target cluster")
            return False

        # Update cluster_id in index
        old_cluster_id = index.cluster_id
        index.cluster_id = target_cluster.id
        index.metadata["promoted_at"] = time.time()
        index.metadata["original_cluster"] = old_cluster_id

        self._index_store.update_shard_index(shard_id, index)

        # Move to appropriate chunk in target cluster
        chunk_name = self._get_chunk_name(index)
        chunk = self._index_store.get_chunk_by_name(chunk_name)
        if not chunk:
            chunk = MemoryChunk.create(
                name=chunk_name,
                cluster_id=target_cluster.id,
            )
            self._index_store.save_chunk(chunk)
            target_cluster.add_chunk(chunk.id)
            self._index_store.save_cluster(target_cluster)

        # Update chunk membership
        chunk.add_shard(shard_id)
        self._index_store.save_chunk(chunk)

        logger.debug(f"Promoted shard {shard_id} to {target_cluster_type.value}")
        return True

    def _get_target_cluster_type(self, index: ShardIndex) -> ClusterType:
        """Determine target cluster based on shard type."""
        if index.shard_type == ShardType.PREFERENCE:
            return ClusterType.IDENTITY
        elif index.shard_type == ShardType.SKILL:
            return ClusterType.CAPABILITY
        elif index.shard_type == ShardType.FACT:
            return ClusterType.KNOWLEDGE
        elif index.shard_type == ShardType.EVENT:
            return ClusterType.EXPERIENCE
        else:
            return ClusterType.KNOWLEDGE

    def _get_chunk_name(self, index: ShardIndex) -> str:
        """Get chunk name for promoted shard."""
        if index.shard_type == ShardType.PREFERENCE:
            return "promoted_preferences"
        elif index.shard_type == ShardType.SKILL:
            return "promoted_skills"
        elif index.shard_type == ShardType.FACT:
            return "promoted_facts"
        return "promoted_general"