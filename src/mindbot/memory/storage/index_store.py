"""JSON index store - lightweight index layer pointing to Markdown content."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from mindbot.memory.types import (
    ChunkType,
    ClusterType,
    MemoryChunk,
    MemoryCluster,
    MemoryProfile,
    ShardIndex,
)
from mindbot.utils import get_logger

logger = get_logger("memory.index_store")


@dataclass
class IndexStoreConfig:
    """Configuration for JSON index store."""

    base_path: str = "~/.mindbot/memory"
    profile_file: str = "profiles.json"
    cluster_file: str = "clusters.json"
    chunk_file: str = "chunks.json"
    shard_index_file: str = "index.json"


class JSONIndexStore:
    """
    JSON index storage - maintains hierarchy structure and shard indices.

    Does NOT store full text content - only metadata and pointers to Markdown.
    """

    def __init__(self, config: IndexStoreConfig | None = None) -> None:
        self._config = config or IndexStoreConfig()
        self._base_path = Path(self._config.base_path).expanduser()
        self._ensure_dirs()

        # In-memory caches
        self._shard_indices: dict[str, ShardIndex] = {}
        self._profiles: dict[str, MemoryProfile] = {}
        self._clusters: dict[str, MemoryCluster] = {}
        self._chunks: dict[str, MemoryChunk] = {}

        # Load existing indices
        self._load_all()

    def _ensure_dirs(self) -> None:
        """Ensure base directory exists."""
        self._base_path.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Shard Index Operations
    # ------------------------------------------------------------------

    def get_shard_index(self, shard_id: str) -> ShardIndex | None:
        """Get shard index by ID."""
        return self._shard_indices.get(shard_id)

    def update_shard_index(self, shard_id: str, index: ShardIndex) -> None:
        """Update or insert shard index."""
        self._shard_indices[shard_id] = index
        self._save_shard_indices()

    def delete_shard_index(self, shard_id: str) -> None:
        """Delete shard index."""
        if shard_id in self._shard_indices:
            del self._shard_indices[shard_id]
            self._save_shard_indices()

    def load_all_indices(self) -> dict[str, ShardIndex]:
        """Load all shard indices."""
        return self._shard_indices.copy()

    def list_shard_ids_by_chunk(self, chunk_id: str) -> list[str]:
        """List all shard IDs belonging to a chunk."""
        return [
            sid for sid, idx in self._shard_indices.items()
            if idx.chunk_id == chunk_id
        ]

    def list_shard_ids_by_cluster(self, cluster_id: str) -> list[str]:
        """List all shard IDs belonging to a cluster."""
        return [
            sid for sid, idx in self._shard_indices.items()
            if idx.cluster_id == cluster_id
        ]

    def search_indices_by_keywords(self, keywords: list[str], limit: int = 50) -> list[ShardIndex]:
        """Search indices by keywords in summary or keywords list."""
        results = []
        for index in self._shard_indices.values():
            # Check if any keyword matches
            match = False
            for kw in keywords:
                if kw.lower() in index.summary.lower():
                    match = True
                    break
                if any(kw.lower() in k.lower() for k in index.keywords):
                    match = True
                    break
            if match:
                results.append(index)
        return results[:limit]

    # ------------------------------------------------------------------
    # Profile Operations
    # ------------------------------------------------------------------

    def load_profile(self, agent_id: str) -> MemoryProfile | None:
        """Load profile by agent ID."""
        return self._profiles.get(agent_id)

    def save_profile(self, profile: MemoryProfile) -> None:
        """Save profile."""
        profile.updated_at = time.time()
        self._profiles[profile.agent_id] = profile
        self._save_profiles()

    def list_profiles(self) -> list[str]:
        """List all profile agent IDs."""
        return list(self._profiles.keys())

    def get_active_profile(self) -> MemoryProfile | None:
        """Get the first/active profile."""
        if not self._profiles:
            return None
        return next(iter(self._profiles.values()))

    # ------------------------------------------------------------------
    # Cluster Operations
    # ------------------------------------------------------------------

    def load_cluster(self, cluster_id: str) -> MemoryCluster | None:
        """Load cluster by ID."""
        return self._clusters.get(cluster_id)

    def save_cluster(self, cluster: MemoryCluster) -> None:
        """Save cluster."""
        cluster.updated_at = time.time()
        self._clusters[cluster.id] = cluster
        self._save_clusters()

    def list_clusters(self, profile_id: str | None = None) -> list[str]:
        """List cluster IDs, optionally filtered by profile."""
        if profile_id:
            return [
                cid for cid, c in self._clusters.items()
                if c.profile_id == profile_id
            ]
        return list(self._clusters.keys())

    def get_cluster_by_type(self, cluster_type: ClusterType) -> MemoryCluster | None:
        """Get cluster by type."""
        for cluster in self._clusters.values():
            if cluster.cluster_type == cluster_type:
                return cluster
        return None

    # ------------------------------------------------------------------
    # Chunk Operations
    # ------------------------------------------------------------------

    def load_chunk(self, chunk_id: str) -> MemoryChunk | None:
        """Load chunk by ID."""
        return self._chunks.get(chunk_id)

    def save_chunk(self, chunk: MemoryChunk) -> None:
        """Save chunk."""
        chunk.updated_at = time.time()
        self._chunks[chunk.id] = chunk
        self._save_chunks()

    def list_chunks(self, cluster_id: str | None = None) -> list[str]:
        """List chunk IDs, optionally filtered by cluster."""
        if cluster_id:
            return [
                cid for cid, c in self._chunks.items()
                if c.cluster_id == cluster_id
            ]
        return list(self._chunks.keys())

    def get_chunk_by_name(self, name: str) -> MemoryChunk | None:
        """Get chunk by name."""
        for chunk in self._chunks.values():
            if chunk.name == name:
                return chunk
        return None

    # ------------------------------------------------------------------
    # Hierarchy Maintenance
    # ------------------------------------------------------------------

    def rebuild_hierarchy_stats(self) -> None:
        """Rebuild statistics for all hierarchy levels."""
        # Update chunk shard counts
        for chunk in self._chunks.values():
            shard_ids = self.list_shard_ids_by_chunk(chunk.id)
            chunk.total_access = sum(
                self._shard_indices.get(sid, ShardIndex(shard_id="", markdown_path="")).access_count
                for sid in shard_ids
            )

        # Update cluster stats
        for cluster in self._clusters.values():
            cluster.total_chunks = len(cluster.chunk_ids)
            all_shard_ids = self.list_shard_ids_by_cluster(cluster.id)
            cluster.total_shards = len(all_shard_ids)

        # Update profile stats
        for profile in self._profiles.values():
            profile.total_clusters = len(profile.cluster_ids)
            total_shards = 0
            total_chunks = 0
            for cid in profile.cluster_ids:
                cluster = self._clusters.get(cid)
                if cluster:
                    total_shards += cluster.total_shards
                    total_chunks += cluster.total_chunks
            profile.total_shards = total_shards
            profile.total_chunks = total_chunks

        self._save_all()

    def ensure_default_structure(self, agent_id: str, agent_name: str = "DefaultAgent") -> MemoryProfile:
        """Ensure default profile and clusters exist."""
        profile = self.load_profile(agent_id)
        if not profile:
            profile = MemoryProfile.create(agent_id=agent_id, agent_name=agent_name)
            self.save_profile(profile)

            # Create default clusters
            for cluster_type in ClusterType:
                cluster = MemoryCluster.create(
                    name=cluster_type.value,
                    cluster_type=cluster_type,
                    profile_id=agent_id,
                )
                self.save_cluster(cluster)
                profile.add_cluster(cluster.id)

            self.save_profile(profile)
            logger.info(f"Created default profile and clusters for agent {agent_id}")

        return profile

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_all(self) -> None:
        """Load all indices from JSON files."""
        self._load_shard_indices()
        self._load_profiles()
        self._load_clusters()
        self._load_chunks()

    def _save_all(self) -> None:
        """Save all indices to JSON files."""
        self._save_shard_indices()
        self._save_profiles()
        self._save_clusters()
        self._save_chunks()

    def _load_shard_indices(self) -> None:
        """Load shard indices from JSON file."""
        file_path = self._base_path / self._config.shard_index_file
        if not file_path.exists():
            return
        try:
            with file_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                index = ShardIndex.from_dict(item)
                self._shard_indices[index.shard_id] = index
            logger.debug(f"Loaded {len(self._shard_indices)} shard indices")
        except Exception as e:
            logger.warning(f"Failed to load shard indices: {e}")

    def _save_shard_indices(self) -> None:
        """Save shard indices to JSON file."""
        file_path = self._base_path / self._config.shard_index_file
        data = [idx.to_dict() for idx in self._shard_indices.values()]
        with file_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.debug(f"Saved {len(data)} shard indices")

    def _load_profiles(self) -> None:
        """Load profiles from JSON file."""
        file_path = self._base_path / self._config.profile_file
        if not file_path.exists():
            return
        try:
            with file_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            for agent_id, item in data.items():
                profile = MemoryProfile(
                    agent_id=agent_id,
                    agent_name=item.get("agent_name", ""),
                    profile_version=item.get("profile_version", "1.0"),
                    identity_definition=item.get("identity_definition", ""),
                    personality_traits=item.get("personality_traits", {}),
                    core_values=item.get("core_values", []),
                    communication_style=item.get("communication_style", ""),
                    cluster_ids=item.get("cluster_ids", []),
                    total_shards=item.get("total_shards", 0),
                    total_chunks=item.get("total_chunks", 0),
                    total_clusters=item.get("total_clusters", 0),
                    compatibility_version=item.get("compatibility_version", "mindbot-v1.0"),
                    created_at=item.get("created_at", time.time()),
                    updated_at=item.get("updated_at", time.time()),
                    last_migration_at=item.get("last_migration_at"),
                    migration_count=item.get("migration_count", 0),
                    origin_agent=item.get("origin_agent"),
                    metadata=item.get("metadata", {}),
                )
                self._profiles[agent_id] = profile
            logger.debug(f"Loaded {len(self._profiles)} profiles")
        except Exception as e:
            logger.warning(f"Failed to load profiles: {e}")

    def _save_profiles(self) -> None:
        """Save profiles to JSON file."""
        file_path = self._base_path / self._config.profile_file
        data = {}
        for profile in self._profiles.values():
            data[profile.agent_id] = {
                "agent_name": profile.agent_name,
                "profile_version": profile.profile_version,
                "identity_definition": profile.identity_definition,
                "personality_traits": profile.personality_traits,
                "core_values": profile.core_values,
                "communication_style": profile.communication_style,
                "cluster_ids": profile.cluster_ids,
                "total_shards": profile.total_shards,
                "total_chunks": profile.total_chunks,
                "total_clusters": profile.total_clusters,
                "compatibility_version": profile.compatibility_version,
                "created_at": profile.created_at,
                "updated_at": profile.updated_at,
                "last_migration_at": profile.last_migration_at,
                "migration_count": profile.migration_count,
                "origin_agent": profile.origin_agent,
                "metadata": profile.metadata,
            }
        with file_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.debug(f"Saved {len(data)} profiles")

    def _load_clusters(self) -> None:
        """Load clusters from JSON file."""
        file_path = self._base_path / self._config.cluster_file
        if not file_path.exists():
            return
        try:
            with file_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                cluster = MemoryCluster(
                    id=item["id"],
                    name=item.get("name", ""),
                    cluster_type=ClusterType(item.get("cluster_type", "knowledge")),
                    profile_id=item.get("profile_id", ""),
                    chunk_ids=item.get("chunk_ids", []),
                    total_shards=item.get("total_shards", 0),
                    total_chunks=item.get("total_chunks", 0),
                    migration_priority=item.get("migration_priority", 3),
                    is_core=item.get("is_core", False),
                    created_at=item.get("created_at", time.time()),
                    updated_at=item.get("updated_at", time.time()),
                    summary=item.get("summary", ""),
                    metadata=item.get("metadata", {}),
                )
                self._clusters[cluster.id] = cluster
            logger.debug(f"Loaded {len(self._clusters)} clusters")
        except Exception as e:
            logger.warning(f"Failed to load clusters: {e}")

    def _save_clusters(self) -> None:
        """Save clusters to JSON file."""
        file_path = self._base_path / self._config.cluster_file
        data = []
        for cluster in self._clusters.values():
            data.append({
                "id": cluster.id,
                "name": cluster.name,
                "cluster_type": cluster.cluster_type.value,
                "profile_id": cluster.profile_id,
                "chunk_ids": cluster.chunk_ids,
                "total_shards": cluster.total_shards,
                "total_chunks": cluster.total_chunks,
                "migration_priority": cluster.migration_priority,
                "is_core": cluster.is_core,
                "created_at": cluster.created_at,
                "updated_at": cluster.updated_at,
                "summary": cluster.summary,
                "metadata": cluster.metadata,
            })
        with file_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.debug(f"Saved {len(data)} clusters")

    def _load_chunks(self) -> None:
        """Load chunks from JSON file."""
        file_path = self._base_path / self._config.chunk_file
        if not file_path.exists():
            return
        try:
            with file_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                chunk = MemoryChunk(
                    id=item["id"],
                    name=item.get("name", ""),
                    description=item.get("description", ""),
                    cluster_id=item.get("cluster_id", ""),
                    shard_ids=item.get("shard_ids", []),
                    chunk_type=ChunkType(item.get("chunk_type", "knowledge")),
                    total_access=item.get("total_access", 0),
                    importance_score=item.get("importance_score", 0.5),
                    is_exportable=item.get("is_exportable", True),
                    created_at=item.get("created_at", time.time()),
                    updated_at=item.get("updated_at", time.time()),
                    summary=item.get("summary", ""),
                    metadata=item.get("metadata", {}),
                )
                self._chunks[chunk.id] = chunk
            logger.debug(f"Loaded {len(self._chunks)} chunks")
        except Exception as e:
            logger.warning(f"Failed to load chunks: {e}")

    def _save_chunks(self) -> None:
        """Save chunks to JSON file."""
        file_path = self._base_path / self._config.chunk_file
        data = []
        for chunk in self._chunks.values():
            data.append({
                "id": chunk.id,
                "name": chunk.name,
                "description": chunk.description,
                "cluster_id": chunk.cluster_id,
                "shard_ids": chunk.shard_ids,
                "chunk_type": chunk.chunk_type.value,
                "total_access": chunk.total_access,
                "importance_score": chunk.importance_score,
                "is_exportable": chunk.is_exportable,
                "created_at": chunk.created_at,
                "updated_at": chunk.updated_at,
                "summary": chunk.summary,
                "metadata": chunk.metadata,
            })
        with file_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.debug(f"Saved {len(data)} chunks")

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def clear_all(self) -> None:
        """Clear all indices (for testing/reset)."""
        self._shard_indices.clear()
        self._profiles.clear()
        self._clusters.clear()
        self._chunks.clear()
        self._save_all()

    def get_stats(self) -> dict[str, int]:
        """Get store statistics."""
        return {
            "profiles": len(self._profiles),
            "clusters": len(self._clusters),
            "chunks": len(self._chunks),
            "shards": len(self._shard_indices),
        }