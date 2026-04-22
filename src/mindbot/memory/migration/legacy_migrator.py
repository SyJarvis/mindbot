"""Legacy migrator - migrate from old SQLite memory.db to new structure."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from mindbot.memory.storage.content_store import MarkdownContentStore
from mindbot.memory.storage.index_store import JSONIndexStore
from mindbot.memory.types import (
    ChunkType,
    ClusterType,
    MemoryChunk,
    MemoryCluster,
    ShardIndex,
    ShardSource,
    ShardType,
)
from mindbot.utils import get_logger

logger = get_logger("migration.legacy")


class LegacyMigrator:
    """Migrate from old SQLite-based memory system to new four-tier structure."""

    def __init__(
        self,
        index_store: JSONIndexStore,
        content_store: MarkdownContentStore,
    ) -> None:
        self._index_store = index_store
        self._content_store = content_store

    def migrate_from_sqlite(
        self,
        sqlite_path: str,
        target_agent_id: str = "legacy-import",
        target_agent_name: str = "LegacyBot",
    ) -> dict[str, Any]:
        """
        Migrate old memory.db to new structure.

        Args:
            sqlite_path: Path to old memory.db file
            target_agent_id: Agent ID for migrated data
            target_agent_name: Agent name

        Returns:
            Migration report
        """
        sqlite_path = Path(sqlite_path).expanduser()
        if not sqlite_path.exists():
            raise FileNotFoundError(f"SQLite file not found: {sqlite_path}")

        report = {
            "source_path": str(sqlite_path),
            "migrated_shards": 0,
            "migrated_chunks": 0,
            "errors": [],
            "started_at": time.time(),
        }

        # Connect to old database
        conn = sqlite3.connect(str(sqlite_path))
        conn.row_factory = sqlite3.Row

        # Create profile
        profile = self._index_store.ensure_default_structure(target_agent_id, target_agent_name)

        # Map old sources to new cluster types
        source_to_cluster = {
            "short_term": ClusterType.EXPERIENCE,
            "long_term": ClusterType.KNOWLEDGE,
            "fact": ClusterType.KNOWLEDGE,
        }

        # Map old chunk_type to new shard type
        chunk_type_to_shard = {
            "conversation": ShardType.DIALOGUE,
            "summary": ShardType.FACT,
            "fact": ShardType.FACT,
            "extract": ShardType.FACT,
        }

        # Create default clusters for each source type
        cluster_map: dict[str, MemoryCluster] = {}
        for source, cluster_type in source_to_cluster.items():
            cluster = self._index_store.get_cluster_by_type(cluster_type)
            if not cluster:
                cluster = MemoryCluster.create(
                    name=cluster_type.value,
                    cluster_type=cluster_type,
                    profile_id=target_agent_id,
                )
                self._index_store.save_cluster(cluster)
                profile.add_cluster(cluster.id)
                self._index_store.save_profile(profile)
            cluster_map[source] = cluster

        # Read all old chunks
        try:
            rows = conn.execute(
                "SELECT * FROM memory_chunks ORDER BY created_at DESC"
            ).fetchall()
        except sqlite3.DatabaseError as e:
            report["errors"].append(f"Database read error: {e}")
            conn.close()
            return report

        # Group by date for chunking
        date_chunks: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            try:
                date_val = row["date"] if "date" in row.keys() else None
            except (KeyError, IndexError):
                date_val = None
            if not date_val:
                date_val = time.strftime("%Y-%m-%d", time.localtime(row["created_at"]))
            source = row["source"] or "short_term"
            key = f"{source}_{date_val}"
            if key not in date_chunks:
                date_chunks[key] = []
            date_chunks[key].append(row)

        # Create chunks and shards
        for key, rows_in_chunk in date_chunks.items():
            source, date = key.split("_", 1) if "_" in key else ("short_term", key)
            cluster = cluster_map.get(source, cluster_map["short_term"])

            # Create chunk
            chunk_name = f"{source}_{date}"
            chunk = MemoryChunk.create(
                name=chunk_name,
                cluster_id=cluster.id,
                chunk_type=ChunkType.HISTORY if source == "short_term" else ChunkType.KNOWLEDGE,
            )
            self._index_store.save_chunk(chunk)
            cluster.add_chunk(chunk.id)
            self._index_store.save_cluster(cluster)
            report["migrated_chunks"] += 1

            # Create shards for each row
            for row in rows_in_chunk:
                try:
                    shard_id = uuid.uuid4().hex
                    text = row["text"]

                    # Determine shard type
                    old_type = row["chunk_type"] or "conversation"
                    shard_type = chunk_type_to_shard.get(old_type, ShardType.FACT)

                    # Write to Markdown
                    metadata = json.loads(row["metadata"] or "{}")
                    metadata["legacy_id"] = row["id"]
                    metadata["legacy_source"] = source

                    self._content_store.write_shard(shard_id, text, metadata)

                    # Create index
                    summary = text[:100] if len(text) > 100 else text
                    index = ShardIndex.create(
                        shard_id=shard_id,
                        markdown_path=f"content/shards/{shard_id}.md",
                        summary=summary,
                        shard_type=shard_type,
                        source=ShardSource.IMPORTED,
                        chunk_id=chunk.id,
                        cluster_id=cluster.id,
                    )
                    index.created_at = row["created_at"]
                    index.updated_at = row["updated_at"] or row["created_at"]
                    index.metadata = metadata

                    self._index_store.update_shard_index(shard_id, index)

                    chunk.add_shard(shard_id)
                    report["migrated_shards"] += 1

                except Exception as e:
                    report["errors"].append(f"Row migration error: {e}")

            self._index_store.save_chunk(chunk)

        # Rebuild stats
        self._index_store.rebuild_hierarchy_stats()
        conn.close()

        report["completed_at"] = time.time()
        report["duration_ms"] = int((report["completed_at"] - report["started_at"]) * 1000)

        logger.info(
            f"Legacy migration complete: {report['migrated_chunks']} chunks, "
            f"{report['migrated_shards']} shards"
        )

        return report

    def estimate_source_count(self, sqlite_path: str) -> dict[str, int]:
        """Count records in source SQLite database."""
        sqlite_path = Path(sqlite_path).expanduser()
        if not sqlite_path.exists():
            return {"total": 0}

        conn = sqlite3.connect(str(sqlite_path))
        try:
            total = conn.execute("SELECT COUNT(*) FROM memory_chunks").fetchone()[0]
            short_term = conn.execute(
                "SELECT COUNT(*) FROM memory_chunks WHERE source = 'short_term'"
            ).fetchone()[0]
            long_term = conn.execute(
                "SELECT COUNT(*) FROM memory_chunks WHERE source = 'long_term'"
            ).fetchone()[0]
            conn.close()
            return {
                "total": total,
                "short_term": short_term,
                "long_term": long_term,
            }
        except Exception:
            conn.close()
            return {"total": 0}