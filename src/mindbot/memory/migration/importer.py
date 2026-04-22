"""Memory importer - import Agent identity from migration package."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from mindbot.memory.migration.package import MigrationPackage
from mindbot.memory.storage.content_store import MarkdownContentStore
from mindbot.memory.storage.index_store import JSONIndexStore
from mindbot.memory.storage.vector_store import VectorStore
from mindbot.memory.types import (
    ChunkType,
    ClusterType,
    MemoryChunk,
    MemoryCluster,
    MemoryProfile,
    ShardIndex,
    ShardSource,
    ShardType,
)
from mindbot.utils import get_logger

logger = get_logger("migration.importer")


@dataclass
class ImportOptions:
    """Options for import operation."""

    merge_strategy: str = "replace"     # replace | merge | keep_both
    new_agent_id: str | None = None      # Override agent ID
    new_agent_name: str | None = None    # Override agent name
    import_vectors: bool = True           # Import vector data
    skip_archived: bool = True            # Skip archived shards


class MemoryImporter:
    """Import migration package into current memory system."""

    def __init__(
        self,
        index_store: JSONIndexStore,
        content_store: MarkdownContentStore,
        vector_store: VectorStore | None = None,
    ) -> None:
        self._index_store = index_store
        self._content_store = content_store
        self._vector_store = vector_store

    def import_package(
        self,
        package: MigrationPackage,
        options: ImportOptions | None = None,
    ) -> dict[str, Any]:
        """
        Import migration package into memory system.

        Args:
            package: MigrationPackage to import
            options: Import configuration

        Returns:
            Import report with statistics
        """
        opts = options or ImportOptions()

        # Verify package format
        if package.format != "mindbot-memory-v1.0":
            logger.warning(f"Unknown package format: {package.format}")

        # Verify checksum
        expected_checksum = package.compute_checksum()
        if package.checksum and package.checksum != expected_checksum:
            logger.warning(f"Checksum mismatch, package may be corrupted")

        report = {
            "imported_clusters": 0,
            "imported_chunks": 0,
            "imported_shards": 0,
            "imported_vectors": 0,
            "skipped": 0,
            "errors": [],
            "started_at": time.time(),
        }

        # Determine target agent ID
        target_id = opts.new_agent_id or package.profile.agent_id if package.profile else f"imported-{uuid.uuid4().hex[:8]}"
        target_name = opts.new_agent_name or package.profile.agent_name if package.profile else "Imported Agent"

        # Create or update profile
        existing_profile = self._index_store.load_profile(target_id)
        if existing_profile and opts.merge_strategy == "replace":
            # Clear existing data for replace strategy
            self._clear_profile_data(existing_profile)

        # Create new profile
        new_profile = MemoryProfile.create(
            agent_id=target_id,
            agent_name=target_name,
            identity_definition=package.profile.identity_definition if package.profile else "",
        )
        if package.profile:
            new_profile.personality_traits = package.profile.personality_traits
            new_profile.core_values = package.profile.core_values
            new_profile.communication_style = package.profile.communication_style
            new_profile.origin_agent = package.source_agent_id
            new_profile.migration_count = 1

        self._index_store.save_profile(new_profile)

        # ID mapping for imported entities
        cluster_id_map: dict[str, str] = {}
        chunk_id_map: dict[str, str] = {}
        shard_id_map: dict[str, str] = {}

        # Import clusters
        for cluster_data in package.clusters:
            new_id = uuid.uuid4().hex
            cluster_id_map[cluster_data.cluster_id] = new_id

            cluster = MemoryCluster.create(
                name=cluster_data.name,
                cluster_type=ClusterType(cluster_data.cluster_type),
                profile_id=target_id,
            )
            cluster.id = new_id
            cluster.is_core = cluster_data.is_core
            cluster.migration_priority = cluster_data.migration_priority
            cluster.summary = cluster_data.summary

            self._index_store.save_cluster(cluster)
            new_profile.add_cluster(new_id)
            report["imported_clusters"] += 1

        self._index_store.save_profile(new_profile)

        # Import chunks
        for chunk_data in package.chunks:
            new_id = uuid.uuid4().hex
            chunk_id_map[chunk_data.chunk_id] = new_id

            new_cluster_id = cluster_id_map.get(chunk_data.cluster_id, "")

            chunk = MemoryChunk.create(
                name=chunk_data.name,
                cluster_id=new_cluster_id,
                chunk_type=ChunkType(chunk_data.chunk_type),
                description=chunk_data.description,
            )
            chunk.id = new_id
            chunk.created_at = chunk_data.created_at
            chunk.updated_at = chunk_data.updated_at

            self._index_store.save_chunk(chunk)
            report["imported_chunks"] += 1

        # Import shards
        for shard_data in package.shards:
            # Skip archived if requested
            if shard_data.is_archived and opts.skip_archived:
                report["skipped"] += 1
                continue

            new_id = uuid.uuid4().hex
            shard_id_map[shard_data.shard_id] = new_id

            new_cluster_id = cluster_id_map.get(shard_data.cluster_id, "")
            new_chunk_id = chunk_id_map.get(shard_data.chunk_id, "")

            # Write content to Markdown
            self._content_store.write_shard(new_id, shard_data.text, shard_data.metadata)

            # Create index entry
            summary = shard_data.text[:100] if len(shard_data.text) > 100 else shard_data.text
            index = ShardIndex.create(
                shard_id=new_id,
                markdown_path=f"content/shards/{new_id}.md",
                summary=summary,
                shard_type=ShardType(shard_data.shard_type),
                source=ShardSource(shard_data.source),
                chunk_id=new_chunk_id,
                cluster_id=new_cluster_id,
            )
            index.created_at = shard_data.created_at
            index.updated_at = shard_data.updated_at
            index.access_count = shard_data.access_count
            index.forget_score = shard_data.forget_score
            index.is_archived = shard_data.is_archived
            index.is_permanent = shard_data.is_permanent
            index.metadata["imported_from"] = shard_data.shard_id

            self._index_store.update_shard_index(new_id, index)

            # Update chunk membership
            if new_chunk_id:
                chunk = self._index_store.load_chunk(new_chunk_id)
                if chunk:
                    chunk.add_shard(new_id)
                    self._index_store.save_chunk(chunk)

            # Import vector if available
            if opts.import_vectors and self._vector_store and package.vectors:
                old_vector = package.vectors.get(shard_data.shard_id)
                if old_vector:
                    self._vector_store.insert(new_id, old_vector, metadata={
                        "summary": summary,
                        "shard_type": shard_data.shard_type,
                        "chunk_id": new_chunk_id,
                        "cluster_id": new_cluster_id,
                    })
                    report["imported_vectors"] += 1

            report["imported_shards"] += 1

        # Rebuild stats
        self._index_store.rebuild_hierarchy_stats()

        report["completed_at"] = time.time()
        report["duration_ms"] = int((report["completed_at"] - report["started_at"]) * 1000)

        logger.info(
            f"Imported package: {report['imported_clusters']} clusters, "
            f"{report['imported_chunks']} chunks, "
            f"{report['imported_shards']} shards"
        )

        return report

    def import_from_file(
        self,
        file_path: str,
        options: ImportOptions | None = None,
    ) -> dict[str, Any]:
        """Import from JSON file."""
        package = MigrationPackage.load_from_file(file_path)
        return self.import_package(package, options)

    def _clear_profile_data(self, profile: MemoryProfile) -> None:
        """Clear existing data for a profile (for replace strategy)."""
        # Delete all shards, chunks, clusters
        for cluster_id in profile.cluster_ids:
            cluster = self._index_store.load_cluster(cluster_id)
            if cluster:
                for chunk_id in cluster.chunk_ids:
                    chunk = self._index_store.load_chunk(chunk_id)
                    if chunk:
                        for shard_id in chunk.shard_ids:
                            self._content_store.delete_shard(shard_id)
                            self._index_store.delete_shard_index(shard_id)
                            if self._vector_store:
                                try:
                                    self._vector_store.delete(shard_id)
                                except Exception:
                                    pass
                        self._index_store.save_chunk(chunk)  # Update with empty shards
                self._index_store.save_cluster(cluster)  # Update with empty chunks