"""Migration package data structures."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mindbot.utils import get_logger

logger = get_logger("migration.package")


@dataclass
class ShardData:
    """Shard data for migration (full content included)."""

    shard_id: str
    text: str                         # Full content
    shard_type: str                    # Enum value
    source: str                        # Enum value
    cluster_id: str
    chunk_id: str
    created_at: float
    updated_at: float
    access_count: int = 0
    forget_score: float = 0.0
    is_archived: bool = False
    is_permanent: bool = False
    metadata: dict = field(default_factory=dict)


@dataclass
class ChunkData:
    """Chunk data for migration."""

    chunk_id: str
    name: str
    cluster_id: str
    shard_ids: list[str] = field(default_factory=list)
    description: str = ""
    chunk_type: str = "knowledge"
    created_at: float = 0.0
    updated_at: float = 0.0


@dataclass
class ClusterData:
    """Cluster data for migration."""

    cluster_id: str
    name: str
    cluster_type: str
    profile_id: str
    chunk_ids: list[str] = field(default_factory=list)
    is_core: bool = False
    migration_priority: int = 3
    summary: str = ""


@dataclass
class ProfileData:
    """Profile data for migration."""

    agent_id: str
    agent_name: str
    profile_version: str = "1.0"
    identity_definition: str = ""
    personality_traits: dict = field(default_factory=dict)
    core_values: list[str] = field(default_factory=list)
    communication_style: str = ""
    cluster_ids: list[str] = field(default_factory=list)
    created_at: float = 0.0


@dataclass
class MigrationPackage:
    """
    Complete migration package for Agent identity transfer.

    Contains all data needed to recreate an Agent in a new environment:
    - Profile (identity definition)
    - Clusters (functional domains)
    - Chunks (topic aggregations)
    - Shards (atomic memories with full content)
    - Optionally vectors
    """

    format: str = "mindbot-memory-v1.0"
    exported_at: float = field(default_factory=time.time)
    checksum: str = ""

    # Core data
    profile: ProfileData | None = None
    clusters: list[ClusterData] = field(default_factory=list)
    chunks: list[ChunkData] = field(default_factory=list)
    shards: list[ShardData] = field(default_factory=list)

    # Optional vector data
    vectors: dict[str, list[float]] = field(default_factory=dict)  # shard_id → vector
    vector_dimension: int = 0
    vector_model: str = ""

    # Metadata
    source_agent_id: str = ""
    source_version: str = ""
    export_options: dict = field(default_factory=dict)

    def compute_checksum(self) -> str:
        """Compute checksum for package integrity."""
        data = {
            "profile": self.profile.agent_id if self.profile else "",
            "clusters": sorted([c.cluster_id for c in self.clusters]),
            "chunks": sorted([c.chunk_id for c in self.chunks]),
            "shards": sorted([s.shard_id for s in self.shards]),
            "exported_at": self.exported_at,
        }
        content = json.dumps(data, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "format": self.format,
            "exported_at": self.exported_at,
            "checksum": self.checksum,
            "profile": {
                "agent_id": self.profile.agent_id,
                "agent_name": self.profile.agent_name,
                "profile_version": self.profile.profile_version,
                "identity_definition": self.profile.identity_definition,
                "personality_traits": self.profile.personality_traits,
                "core_values": self.profile.core_values,
                "communication_style": self.profile.communication_style,
                "cluster_ids": self.profile.cluster_ids,
                "created_at": self.profile.created_at,
            } if self.profile else None,
            "clusters": [
                {
                    "cluster_id": c.cluster_id,
                    "name": c.name,
                    "cluster_type": c.cluster_type,
                    "profile_id": c.profile_id,
                    "chunk_ids": c.chunk_ids,
                    "is_core": c.is_core,
                    "migration_priority": c.migration_priority,
                    "summary": c.summary,
                }
                for c in self.clusters
            ],
            "chunks": [
                {
                    "chunk_id": c.chunk_id,
                    "name": c.name,
                    "description": c.description,
                    "cluster_id": c.cluster_id,
                    "shard_ids": c.shard_ids,
                    "chunk_type": c.chunk_type,
                    "created_at": c.created_at,
                    "updated_at": c.updated_at,
                }
                for c in self.chunks
            ],
            "shards": [
                {
                    "shard_id": s.shard_id,
                    "text": s.text,
                    "shard_type": s.shard_type,
                    "source": s.source,
                    "cluster_id": s.cluster_id,
                    "chunk_id": s.chunk_id,
                    "created_at": s.created_at,
                    "updated_at": s.updated_at,
                    "access_count": s.access_count,
                    "forget_score": s.forget_score,
                    "is_archived": s.is_archived,
                    "is_permanent": s.is_permanent,
                    "metadata": s.metadata,
                }
                for s in self.shards
            ],
            "vectors": self.vectors if self.vectors else None,
            "vector_dimension": self.vector_dimension,
            "vector_model": self.vector_model,
            "source_agent_id": self.source_agent_id,
            "source_version": self.source_version,
            "export_options": self.export_options,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MigrationPackage:
        """Deserialize from dictionary."""
        pkg = cls(
            format=data.get("format", "mindbot-memory-v1.0"),
            exported_at=data.get("exported_at", time.time()),
            checksum=data.get("checksum", ""),
            source_agent_id=data.get("source_agent_id", ""),
            source_version=data.get("source_version", ""),
            vector_dimension=data.get("vector_dimension", 0),
            vector_model=data.get("vector_model", ""),
            export_options=data.get("export_options", {}),
        )

        # Profile
        if data.get("profile"):
            p = data["profile"]
            pkg.profile = ProfileData(
                agent_id=p["agent_id"],
                agent_name=p["agent_name"],
                profile_version=p.get("profile_version", "1.0"),
                identity_definition=p.get("identity_definition", ""),
                personality_traits=p.get("personality_traits", {}),
                core_values=p.get("core_values", []),
                communication_style=p.get("communication_style", ""),
                cluster_ids=p.get("cluster_ids", []),
                created_at=p.get("created_at", time.time()),
            )

        # Clusters
        for c in data.get("clusters", []):
            pkg.clusters.append(ClusterData(
                cluster_id=c["cluster_id"],
                name=c["name"],
                cluster_type=c["cluster_type"],
                profile_id=c["profile_id"],
                chunk_ids=c.get("chunk_ids", []),
                is_core=c.get("is_core", False),
                migration_priority=c.get("migration_priority", 3),
                summary=c.get("summary", ""),
            ))

        # Chunks
        for c in data.get("chunks", []):
            pkg.chunks.append(ChunkData(
                chunk_id=c["chunk_id"],
                name=c["name"],
                description=c.get("description", ""),
                cluster_id=c["cluster_id"],
                shard_ids=c.get("shard_ids", []),
                chunk_type=c.get("chunk_type", "knowledge"),
                created_at=c.get("created_at", time.time()),
                updated_at=c.get("updated_at", time.time()),
            ))

        # Shards
        for s in data.get("shards", []):
            pkg.shards.append(ShardData(
                shard_id=s["shard_id"],
                text=s["text"],
                shard_type=s["shard_type"],
                source=s["source"],
                cluster_id=s["cluster_id"],
                chunk_id=s["chunk_id"],
                created_at=s["created_at"],
                updated_at=s["updated_at"],
                access_count=s.get("access_count", 0),
                forget_score=s.get("forget_score", 0.0),
                is_archived=s.get("is_archived", False),
                is_permanent=s.get("is_permanent", False),
                metadata=s.get("metadata", {}),
            ))

        # Vectors
        pkg.vectors = data.get("vectors", {})

        return pkg

    def save_to_file(self, path: str | Path) -> Path:
        """Save package to JSON file."""
        path = Path(path)
        self.checksum = self.compute_checksum()
        with path.open("w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        logger.info(f"Saved migration package to {path}")
        return path

    @classmethod
    def load_from_file(cls, path: str | Path) -> MigrationPackage:
        """Load package from JSON file."""
        path = Path(path)
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        pkg = cls.from_dict(data)

        # Verify checksum
        expected = pkg.compute_checksum()
        if pkg.checksum and pkg.checksum != expected:
            logger.warning(f"Checksum mismatch: expected {expected}, got {pkg.checksum}")

        return pkg

    def get_stats(self) -> dict[str, int]:
        """Get package statistics."""
        return {
            "clusters": len(self.clusters),
            "chunks": len(self.chunks),
            "shards": len(self.shards),
            "vectors": len(self.vectors) if self.vectors else 0,
            "total_content_chars": sum(len(s.text) for s in self.shards),
        }