"""Memory exporter - export Agent identity as migration package."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from mindbot.memory.migration.package import (
    ChunkData,
    ClusterData,
    MigrationPackage,
    ProfileData,
    ShardData,
)
from mindbot.memory.storage.content_store import MarkdownContentStore
from mindbot.memory.storage.index_store import JSONIndexStore
from mindbot.memory.storage.vector_store import VectorStore
from mindbot.utils import get_logger

logger = get_logger("migration.exporter")


@dataclass
class ExportOptions:
    """Options for export operation."""

    include_vectors: bool = False       # Export vector embeddings
    include_archived: bool = False       # Export archived shards
    include_metadata: bool = True        # Export full metadata
    compress_text: bool = False          # Compress text content
    max_shards: int = 1000               # Limit shard count


class MemoryExporter:
    """Export Agent memory profile as migration package."""

    def __init__(
        self,
        index_store: JSONIndexStore,
        content_store: MarkdownContentStore,
        vector_store: VectorStore | None = None,
    ) -> None:
        self._index_store = index_store
        self._content_store = content_store
        self._vector_store = vector_store

    def export(
        self,
        agent_id: str | None = None,
        options: ExportOptions | None = None,
    ) -> MigrationPackage:
        """
        Export Agent profile and all memories to migration package.

        Args:
            agent_id: Specific agent to export (None = active profile)
            options: Export configuration

        Returns:
            MigrationPackage with all data
        """
        opts = options or ExportOptions()

        # Get profile
        profile = self._index_store.load_profile(agent_id) if agent_id else self._index_store.get_active_profile()
        if not profile:
            raise ValueError(f"Profile not found: {agent_id}")

        package = MigrationPackage(
            source_agent_id=profile.agent_id,
            source_version=profile.profile_version,
            exported_at=time.time(),
            export_options={
                "include_vectors": opts.include_vectors,
                "include_archived": opts.include_archived,
            },
        )

        # Export profile
        package.profile = ProfileData(
            agent_id=profile.agent_id,
            agent_name=profile.agent_name,
            profile_version=profile.profile_version,
            identity_definition=profile.identity_definition,
            personality_traits=profile.personality_traits,
            core_values=profile.core_values,
            communication_style=profile.communication_style,
            cluster_ids=profile.cluster_ids,
            created_at=profile.created_at,
        )

        # Export clusters
        for cluster_id in profile.cluster_ids:
            cluster = self._index_store.load_cluster(cluster_id)
            if cluster:
                package.clusters.append(ClusterData(
                    cluster_id=cluster.id,
                    name=cluster.name,
                    cluster_type=cluster.cluster_type.value,
                    profile_id=cluster.profile_id,
                    chunk_ids=cluster.chunk_ids,
                    is_core=cluster.is_core,
                    migration_priority=cluster.migration_priority,
                    summary=cluster.summary,
                ))

        # Export chunks and shards
        shard_count = 0
        for cluster in package.clusters:
            for chunk_id in cluster.chunk_ids:
                chunk = self._index_store.load_chunk(chunk_id)
                if not chunk:
                    continue

                package.chunks.append(ChunkData(
                    chunk_id=chunk.id,
                    name=chunk.name,
                    description=chunk.description,
                    cluster_id=chunk.cluster_id,
                    shard_ids=chunk.shard_ids,
                    chunk_type=chunk.chunk_type.value,
                    created_at=chunk.created_at,
                    updated_at=chunk.updated_at,
                ))

                # Export shards for this chunk
                for shard_id in chunk.shard_ids:
                    if shard_count >= opts.max_shards:
                        break

                    index = self._index_store.get_shard_index(shard_id)
                    if not index:
                        continue

                    # Skip archived unless requested
                    if index.is_archived and not opts.include_archived:
                        continue

                    # Read full content
                    content = self._content_store.read_shard(shard_id)
                    if not content:
                        continue

                    package.shards.append(ShardData(
                        shard_id=shard_id,
                        text=content,
                        shard_type=index.shard_type.value,
                        source=index.source.value,
                        cluster_id=index.cluster_id,
                        chunk_id=index.chunk_id,
                        created_at=index.created_at,
                        updated_at=index.updated_at,
                        access_count=index.access_count,
                        forget_score=index.forget_score,
                        is_archived=index.is_archived,
                        is_permanent=index.is_permanent,
                        metadata=index.metadata if opts.include_metadata else {},
                    ))

                    # Export vector if available
                    if opts.include_vectors and self._vector_store:
                        vector = self._vector_store.get_vector(shard_id)
                        if vector:
                            package.vectors[shard_id] = vector
                            package.vector_dimension = len(vector)

                    shard_count += 1

        # Compute checksum
        package.checksum = package.compute_checksum()

        logger.info(
            f"Exported profile {profile.agent_id}: "
            f"{len(package.clusters)} clusters, "
            f"{len(package.chunks)} chunks, "
            f"{len(package.shards)} shards"
        )

        return package

    def export_to_file(
        self,
        file_path: str,
        agent_id: str | None = None,
        options: ExportOptions | None = None,
    ) -> str:
        """Export and save to JSON file."""
        package = self.export(agent_id, options)
        saved_path = package.save_to_file(file_path)
        return str(saved_path)

    def export_summary(self, agent_id: str | None = None) -> dict[str, Any]:
        """Export summary (metadata only, no full content)."""
        opts = ExportOptions(include_vectors=False, include_metadata=False, max_shards=50)
        package = self.export(agent_id, opts)

        # Return summary without full texts
        return {
            "profile": package.profile.agent_name if package.profile else None,
            "clusters": len(package.clusters),
            "chunks": len(package.chunks),
            "shards": len(package.shards),
            "exported_at": package.exported_at,
            "checksum": package.checksum,
        }