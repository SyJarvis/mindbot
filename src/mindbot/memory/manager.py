"""MemoryManager – unified entry point for the four-tier memory system."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mindbot.memory.storage import (
    IndexStoreConfig,
    JSONIndexStore,
    MarkdownContentStore,
)
from mindbot.memory.lifecycle.forgetter import MemoryForgetter
from mindbot.memory.lifecycle.promoter import MemoryPromoter
from mindbot.memory.lifecycle.summarizer import SummaryGenerator
from mindbot.memory.lifecycle.updater import MemoryUpdater
from mindbot.memory.types import (
    ChunkType,
    ClusterType,
    ForgetPolicy,
    ForgetReport,
    MemoryChunk,
    MemoryCluster,
    MemoryHit,
    MemoryProfile,
    MemoryShard,
    ShardIndex,
    ShardSource,
    ShardType,
)
from mindbot.memory.migration.package import MigrationPackage
from mindbot.providers.embeddings.base import Embedder
from mindbot.logging import logger



@dataclass
class MemoryManagerConfig:
    """Configuration for MemoryManager."""

    base_path: str = "~/.mindbot/memory"
    content_path: str = "~/.mindbot/memory/content"
    vector_path: str = "~/.mindbot/vectors"
    default_agent_id: str = "default"
    default_agent_name: str = "MindBot"

    # Vector settings
    enable_vector: bool = True
    vector_dimension: int = 1536


class MemoryManager:
    """
    Four-tier memory system manager.

    Tier structure: Shard -> Chunk -> Cluster -> Profile

    Storage architecture:
    - JSON Index: metadata and hierarchy (JSONIndexStore)
    - Markdown: full content (MarkdownContentStore)
    - LanceDB: vector storage + FTS (LanceVectorStore)
    """

    def __init__(
        self,
        config: MemoryManagerConfig | None = None,
        *,
        embedder: Embedder | None = None,
    ) -> None:
        self._config = config or MemoryManagerConfig()

        # Initialize stores
        index_config = IndexStoreConfig(base_path=self._config.base_path)
        self._index_store = JSONIndexStore(config=index_config)
        self._content_store = MarkdownContentStore(base_path=self._config.content_path)

        # Initialize vector store (optional)
        self._vector_store = None
        self._embedder: Embedder | None = embedder
        self._retriever = None

        if self._config.enable_vector:
            self._init_vector_layer()

        # Ensure default structure
        self._profile = self._index_store.ensure_default_structure(
            agent_id=self._config.default_agent_id,
            agent_name=self._config.default_agent_name,
        )

        # Forget policy (default)
        self._forget_policy = ForgetPolicy()

        # Lifecycle components
        self._summarizer = SummaryGenerator()
        self._updater = MemoryUpdater(
            index_store=self._index_store,
            content_store=self._content_store,
            vector_store=self._vector_store,
        )
        self._forgetter = MemoryForgetter(
            index_store=self._index_store,
            content_store=self._content_store,
            vector_store=self._vector_store,
            policy=self._forget_policy,
        )
        self._promoter = MemoryPromoter(
            index_store=self._index_store,
            content_store=self._content_store,
        )

        logger.info(f"MemoryManager initialized with profile {self._profile.agent_id}")

    @classmethod
    def from_legacy_config(
        cls,
        storage_path: str = "~/.mindbot/data/memory.db",
        markdown_path: str = "~/.mindbot/data/memory",
        short_term_retention_days: int = 7,
        enable_fts: bool = True,
        **kwargs: Any,
    ) -> MemoryManager:
        """
        Create MemoryManager from legacy config parameters.

        For backward compatibility with old AgentBuilder calls.
        Maps legacy paths to new structure.
        """
        # Convert legacy paths to new structure
        base_path = Path(storage_path).expanduser().parent.parent / "memory"
        content_path = base_path / "content"

        config = MemoryManagerConfig(
            base_path=str(base_path),
            content_path=str(content_path),
            enable_vector=False,  # Legacy config doesn't have vector settings
        )
        return cls(config=config)

    @classmethod
    def from_schema_config(
        cls, config_or_memory: Any, *, embedder: Embedder | None = None,
    ) -> MemoryManager:
        """Create MemoryManager from a MindBot configuration.

        Accepts either the root :class:`mindbot.config.schema.Config` (so
        the embedder can be constructed from declared providers) or the
        nested :class:`mindbot.config.schema.MemoryConfig` for callers
        that do not have access to the root configuration.

        Args:
            config_or_memory: Either a root ``Config`` or a ``MemoryConfig``.
                When a ``MemoryConfig`` is provided, ``embedder`` must be
                supplied (or vector layer must be disabled) because we do
                not have the surrounding provider declarations.
            embedder: Optional pre-built embedder.  When ``None`` and a
                root ``Config`` is provided, the builder constructs one
                from ``memory.vector.embedding_model`` and ``providers``.
        """
        # Accept both Config and MemoryConfig for backward compatibility
        if hasattr(config_or_memory, "memory"):
            root_config = config_or_memory
            memory_config = config_or_memory.memory
        else:
            root_config = None
            memory_config = config_or_memory

        config = MemoryManagerConfig(
            base_path=memory_config.base_path,
            content_path=memory_config.content_path,
            vector_path=memory_config.vector.persist_path,
            default_agent_id=memory_config.default_agent_id,
            default_agent_name=memory_config.default_agent_name,
            enable_vector=memory_config.vector.enabled,
            vector_dimension=memory_config.vector.dimension,
        )

        if embedder is None and config.enable_vector and root_config is not None:
            from mindbot.builders.embedder_builder import create_embedder

            try:
                embedder = create_embedder(root_config)
            except Exception as exc:
                logger.warning(
                    "Failed to create embedder from config "
                    "(vector layer will fall back to keyword-only): {}",
                    exc,
                )

        manager = cls(config=config, embedder=embedder)

        # Apply forget policy from config
        if hasattr(memory_config, 'forget_policy'):
            manager._forget_policy = ForgetPolicy(
                access_weight=memory_config.forget_policy.access_weight,
                age_weight=memory_config.forget_policy.age_weight,
                redundancy_weight=memory_config.forget_policy.redundancy_weight,
                density_weight=memory_config.forget_policy.density_weight,
                source_weight=memory_config.forget_policy.source_weight,
                max_age_days=memory_config.forget_policy.max_age_days,
                recent_protection_days=memory_config.forget_policy.recent_protection_days,
                forget_threshold=memory_config.vector.forget_threshold,
                delete_threshold=memory_config.vector.delete_threshold,
                archive_threshold=memory_config.vector.archive_threshold,
            )
            manager._forgetter._policy = manager._forget_policy

        return manager

    def _init_vector_layer(self) -> None:
        """Initialize LanceDB vector store and hybrid retriever.

        The embedder is no longer constructed here – callers inject one
        through :meth:`__init__` (typically via :meth:`from_schema_config`
        which delegates to :func:`mindbot.builders.create_embedder`).
        When no embedder is supplied the vector store still loads but
        recall degrades to keyword/FTS-only signals.
        """
        try:
            from mindbot.memory.retrieval.searcher import HybridRetriever
            from mindbot.memory.storage.lance_store import LanceVectorStore

            dimension = self._config.vector_dimension
            if self._embedder is not None:
                embedder_dim = self._embedder.dimension
                if embedder_dim != dimension:
                    logger.warning(
                        "embedder.dimension={} differs from "
                        "memory.vector.dimension={}; using embedder value "
                        "to stay consistent with LanceDB table schema",
                        embedder_dim,
                        dimension,
                    )
                    dimension = embedder_dim
                    self._config.vector_dimension = embedder_dim

            self._vector_store = LanceVectorStore(
                uri=self._config.vector_path,
                dimension=dimension,
            )

            self._retriever = HybridRetriever(
                vector_store=self._vector_store,
                index_store=self._index_store,
                content_store=self._content_store,
                embedder=self._embedder,
            )

            logger.info(
                "Vector layer initialized (LanceDB, dim={}, embedder={})",
                dimension,
                type(self._embedder).__name__ if self._embedder else "None",
            )
        except Exception as e:
            logger.warning(f"Vector layer initialization failed, falling back to keyword-only: {e}")
            self._vector_store = None
            self._embedder = None
            self._retriever = None

    # ------------------------------------------------------------------
    # Profile Operations
    # ------------------------------------------------------------------

    def get_profile(self) -> MemoryProfile:
        """Get current profile."""
        return self._profile

    def get_cluster(self, cluster_type: ClusterType) -> MemoryCluster | None:
        """Get cluster by type."""
        return self._index_store.get_cluster_by_type(cluster_type)

    def get_chunk(self, chunk_name: str) -> MemoryChunk | None:
        """Get chunk by name."""
        return self._index_store.get_chunk_by_name(chunk_name)

    # ------------------------------------------------------------------
    # Write Operations (API Compatible)
    # ------------------------------------------------------------------

    def append_to_short_term(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> list[MemoryShard]:
        """
        Store content as short-term memory (dialogue/event).

        API compatible with old implementation.
        """
        return self._append_memory(
            content=content,
            shard_type=ShardType.DIALOGUE,
            source=ShardSource.USER_TOLD,
            cluster_type=ClusterType.EXPERIENCE,
            metadata=metadata,
        )

    def promote_to_long_term(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> list[MemoryShard]:
        """
        Promote content to long-term memory (fact/knowledge).

        API compatible with old implementation.
        """
        return self._append_memory(
            content=content,
            shard_type=ShardType.FACT,
            source=ShardSource.USER_TOLD,
            cluster_type=ClusterType.KNOWLEDGE,
            metadata=metadata,
        )

    def append_preference(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryShard:
        """Append a preference memory."""
        shards = self._append_memory(
            content=content,
            shard_type=ShardType.PREFERENCE,
            source=ShardSource.USER_TOLD,
            cluster_type=ClusterType.IDENTITY,
            metadata=metadata,
        )
        return shards[0] if shards else MemoryShard(id="", text="")

    def append_skill(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryShard:
        """Append a skill/capability memory."""
        shards = self._append_memory(
            content=content,
            shard_type=ShardType.SKILL,
            source=ShardSource.USER_TOLD,
            cluster_type=ClusterType.CAPABILITY,
            metadata=metadata,
        )
        return shards[0] if shards else MemoryShard(id="", text="")

    def _append_memory(
        self,
        content: str,
        shard_type: ShardType,
        source: ShardSource,
        cluster_type: ClusterType,
        metadata: dict[str, Any] | None = None,
    ) -> list[MemoryShard]:
        """Internal method to append a memory shard with update logic."""
        md = metadata.copy() if metadata else {}
        md["shard_type"] = shard_type.value
        md["source"] = source.value

        # Generate summary and keywords
        index_data = self._summarizer.generate_index_data(content)
        summary = index_data["summary"]
        keywords = index_data["keywords"]
        content_hash = index_data["content_hash"]
        md["content_hash"] = content_hash

        # Update decision: check for duplicates, merges, corrections
        update_result = self._updater.process(content, shard_type)

        if update_result.action == "ignore":
            logger.debug(f"Ignored duplicate memory (matches {update_result.target_id})")
            existing = self.get_shard(update_result.target_id)
            return [existing] if existing else []

        if update_result.action in ("merge", "correct"):
            # Existing shard was updated in-place by the updater
            logger.info(f"Memory {update_result.action}: {update_result.target_id}")
            existing = self.get_shard(update_result.target_id)
            return [existing] if existing else []

        # store_new or supplement → create new shard
        return self._store_new_shard(
            content=content,
            shard_type=shard_type,
            source=source,
            cluster_type=cluster_type,
            summary=summary,
            keywords=keywords,
            metadata=md,
        )

    def _store_new_shard(
        self,
        content: str,
        shard_type: ShardType,
        source: ShardSource,
        cluster_type: ClusterType,
        summary: str,
        keywords: list[str],
        metadata: dict[str, Any],
    ) -> list[MemoryShard]:
        """Store a new shard to all layers."""
        md = metadata

        # Find or create cluster
        cluster = self._index_store.get_cluster_by_type(cluster_type)
        if not cluster:
            cluster = MemoryCluster.create(
                name=cluster_type.value,
                cluster_type=cluster_type,
                profile_id=self._profile.agent_id,
            )
            self._index_store.save_cluster(cluster)
            self._profile.add_cluster(cluster.id)
            self._index_store.save_profile(self._profile)

        # Create shard
        shard = MemoryShard.create(
            text=content,
            shard_type=shard_type,
            source=source,
            cluster_id=cluster.id,
            metadata=md,
        )

        # Find or create a chunk
        chunk_name = self._get_chunk_name_for_shard(shard_type, cluster_type)
        chunk = self._index_store.get_chunk_by_name(chunk_name)
        if not chunk:
            chunk = MemoryChunk.create(
                name=chunk_name,
                cluster_id=cluster.id,
                chunk_type=self._map_shard_to_chunk_type(shard_type),
            )
            self._index_store.save_chunk(chunk)
            cluster.add_chunk(chunk.id)
            self._index_store.save_cluster(cluster)

        shard.chunk_id = chunk.id

        # 1. Markdown content
        md["chunk_id"] = chunk.id
        md["cluster_id"] = cluster.id
        md["created_at"] = shard.created_at
        file_path = self._content_store.write_shard(shard.id, content, md)
        rel_path = str(file_path.relative_to(file_path.parent.parent.parent))

        # 2. JSON index
        index = ShardIndex.create(
            shard_id=shard.id,
            markdown_path=rel_path,
            summary=summary,
            shard_type=shard_type,
            source=source,
            chunk_id=chunk.id,
            cluster_id=cluster.id,
            keywords=keywords,
            metadata=md,
        )
        self._index_store.update_shard_index(shard.id, index)

        # 3. Update chunk
        chunk.add_shard(shard.id)
        self._index_store.save_chunk(chunk)

        # 4. Write to vector store
        if self._vector_store:
            try:
                self._index_vector(shard.id, content, summary, shard_type.value, chunk.id, cluster.id)
            except Exception as e:
                logger.debug(f"Vector indexing failed for {shard.id}: {e}")

        # 5. Rebuild stats
        self._index_store.rebuild_hierarchy_stats()

        logger.debug(f"Stored shard {shard.id} to {cluster_type.value}/{chunk_name}")
        return [shard]

    # ------------------------------------------------------------------
    # Read Operations (API Compatible)
    # ------------------------------------------------------------------

    async def recall(
        self,
        query: str,
        top_k: int = 5,
        cluster_type: str | None = None,
    ) -> list[MemoryHit]:
        """Hybrid recall returning explainable :class:`MemoryHit` objects.

        This is the single entrypoint for memory retrieval after the
        Memory Recall refactor.  It always runs the full vector + FTS +
        grep + index + recency pipeline when a retriever is available;
        otherwise it falls back to a keyword-only search executed in a
        worker thread so we never block the event loop.
        """
        if self._retriever is not None:
            return await self._retriever.recall(
                query, top_k=top_k, cluster_type=cluster_type,
            )
        return await asyncio.to_thread(self._keyword_recall_sync, query, top_k)

    def _keyword_recall_sync(self, query: str, top_k: int = 5) -> list[MemoryHit]:
        """Synchronous keyword-only fallback returning :class:`MemoryHit`.

        Used when the hybrid retriever is unavailable (no vector layer).
        Exposed only via :meth:`recall`'s ``asyncio.to_thread`` path so
        the public surface stays async.
        """
        matching_ids = self._content_store.search_by_keyword(query, limit=top_k * 3)

        scored: list[tuple[float, ShardIndex, float, float]] = []
        # tuple: (combined_score, index, grep_signal, recency_signal)
        for shard_id in matching_ids:
            index = self._index_store.get_shard_index(shard_id)
            if index is None:
                continue
            grep_signal = 0.0
            if query.lower() in index.summary.lower():
                grep_signal += 3.0
            if index.keywords:
                for kw in index.keywords:
                    if kw.lower() in query.lower():
                        grep_signal += 1.5
            hours = max((time.time() - index.created_at) / 3600.0, 0.0)
            recency_signal = 1.0 / (1.0 + hours / 24.0)
            combined = grep_signal + recency_signal
            scored.append((combined, index, grep_signal, recency_signal))

        scored.sort(key=lambda item: item[0], reverse=True)

        hits: list[MemoryHit] = []
        for combined, index, grep_signal, recency_signal in scored[:top_k]:
            content = self._content_store.read_shard(index.shard_id)
            if not content:
                continue
            index.touch()
            self._index_store.update_shard_index(index.shard_id, index)
            shard = MemoryShard(
                id=index.shard_id,
                text=content,
                shard_type=index.shard_type,
                source=index.source,
                cluster_id=index.cluster_id,
                chunk_id=index.chunk_id,
                created_at=index.created_at,
                updated_at=index.updated_at,
                access_count=index.access_count,
                forget_score=index.forget_score,
                is_archived=index.is_archived,
                is_permanent=index.is_permanent,
                metadata=index.metadata,
            )
            hits.append(MemoryHit(
                shard=shard,
                score=combined,
                grep_score=grep_signal,
                recency_score=recency_signal,
            ))
        return hits

    def get_shard(self, shard_id: str) -> MemoryShard | None:
        """Get a specific shard by ID."""
        index = self._index_store.get_shard_index(shard_id)
        if not index:
            return None

        content = self._content_store.read_shard(shard_id)
        if not content:
            return None

        index.touch()
        self._index_store.update_shard_index(shard_id, index)

        return MemoryShard(
            id=shard_id,
            text=content,
            shard_type=index.shard_type,
            source=index.source,
            cluster_id=index.cluster_id,
            chunk_id=index.chunk_id,
            created_at=index.created_at,
            updated_at=index.updated_at,
            access_count=index.access_count,
            forget_score=index.forget_score,
            is_archived=index.is_archived,
            is_permanent=index.is_permanent,
            metadata=index.metadata,
        )

    # ------------------------------------------------------------------
    # Maintenance Operations (API Compatible)
    # ------------------------------------------------------------------

    def compact(self) -> int:
        """
        Run forget cycle to purge low-value memories.

        API compatible with old implementation (returns count deleted).

        Now uses multi-dimensional scoring instead of simple expiration.
        """
        report = self.run_forget_cycle()
        return len(report.deleted)

    def run_forget_cycle(self) -> ForgetReport:
        """
        Execute forget cycle based on multi-dimensional scoring.

        Delegates to MemoryForgetter for scoring and execution.
        """
        # Update total queries in forgetter
        indices = self._index_store.load_all_indices()
        total_queries = sum(idx.access_count for idx in indices.values()) or 1
        self._forgetter.set_total_queries(total_queries)

        return self._forgetter.run_cycle()

    def run_promotion_cycle(self) -> dict[str, Any]:
        """
        Promote high-value short-term memories to long-term.

        Criteria: high access count, survived initial decay, marked important.
        """
        return self._promoter.run_promotion_cycle()

    def run_maintenance(self) -> dict[str, Any]:
        """
        Full maintenance cycle: promotion + forget.

        Returns combined report from both operations.
        """
        promotion_report = self.run_promotion_cycle()
        forget_report = self.run_forget_cycle()

        return {
            "promoted": promotion_report.get("promoted", []),
            "deleted": forget_report.deleted,
            "archived": forget_report.archived,
            "kept": forget_report.kept,
            "executed_at": time.time(),
        }

    # ------------------------------------------------------------------
    # Utility Methods
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Release resources."""
        # No explicit close needed for JSON/Markdown stores
        logger.debug("MemoryManager closed")

    def get_stats(self) -> dict[str, Any]:
        """Get memory system statistics."""
        index_stats = self._index_store.get_stats()
        content_stats = self._content_store.get_stats()
        stats = {
            "profile": self._profile.agent_name,
            "clusters": index_stats["clusters"],
            "chunks": index_stats["chunks"],
            "shards": index_stats["shards"],
            "content_files": content_stats["shards"],
            "archived": content_stats["archived"],
            "vector_enabled": self._vector_store is not None,
        }
        if self._vector_store:
            stats["vector_count"] = self._vector_store.count()
        return stats

    def _get_chunk_name_for_shard(self, shard_type: ShardType, cluster_type: ClusterType) -> str:
        """Determine chunk name based on shard and cluster type."""
        # Default chunk naming scheme
        if shard_type == ShardType.DIALOGUE:
            date = time.strftime("%Y-%m-%d")
            return f"dialogue_{date}"
        elif shard_type == ShardType.PREFERENCE:
            return "preferences"
        elif shard_type == ShardType.SKILL:
            return "skills"
        elif shard_type == ShardType.FACT:
            return f"facts_{cluster_type.value}"
        elif shard_type == ShardType.EVENT:
            date = time.strftime("%Y-%m")
            return f"events_{date}"
        return "general"

    def _map_shard_to_chunk_type(self, shard_type: ShardType) -> ChunkType:
        """Map shard type to chunk type."""
        mapping = {
            ShardType.DIALOGUE: ChunkType.HISTORY,
            ShardType.PREFERENCE: ChunkType.PREFERENCE,
            ShardType.SKILL: ChunkType.SKILL,
            ShardType.FACT: ChunkType.KNOWLEDGE,
            ShardType.EVENT: ChunkType.HISTORY,
        }
        return mapping.get(shard_type, ChunkType.KNOWLEDGE)

    def _index_vector(
        self,
        shard_id: str,
        text: str,
        summary: str,
        shard_type: str,
        chunk_id: str,
        cluster_id: str,
    ) -> None:
        """Index a shard into the vector store (sync, best-effort)."""
        if not self._vector_store or not self._embedder:
            return

        vector = self._embedder.encode_sync(text)
        self._vector_store.insert(shard_id, vector, metadata={
            "summary": summary,
            "shard_type": shard_type,
            "chunk_id": chunk_id,
            "cluster_id": cluster_id,
        })

    # ------------------------------------------------------------------
    # Migration Operations (New API)
    # ------------------------------------------------------------------

    def export_profile(
        self,
        include_vectors: bool = False,
        include_archived: bool = False,
    ) -> MigrationPackage:
        """Export current profile as MigrationPackage."""
        from mindbot.memory.migration import ExportOptions, MemoryExporter

        exporter = MemoryExporter(
            index_store=self._index_store,
            content_store=self._content_store,
            vector_store=self._vector_store,
        )
        options = ExportOptions(
            include_vectors=include_vectors,
            include_archived=include_archived,
        )
        return exporter.export(options=options)

    def export_to_file(self, file_path: str, include_vectors: bool = False) -> str:
        """Export profile to JSON file."""
        from mindbot.memory.migration import ExportOptions, MemoryExporter

        exporter = MemoryExporter(
            index_store=self._index_store,
            content_store=self._content_store,
            vector_store=self._vector_store,
        )
        options = ExportOptions(include_vectors=include_vectors)
        return exporter.export_to_file(file_path, options=options)

    def import_from_package(
        self,
        package: MigrationPackage,
        new_agent_id: str | None = None,
        new_agent_name: str | None = None,
    ) -> dict[str, Any]:
        """Import from MigrationPackage."""
        from mindbot.memory.migration import ImportOptions, MemoryImporter

        importer = MemoryImporter(
            index_store=self._index_store,
            content_store=self._content_store,
            vector_store=self._vector_store,
        )
        options = ImportOptions(
            new_agent_id=new_agent_id,
            new_agent_name=new_agent_name,
        )
        return importer.import_package(package, options=options)

    def import_from_file(self, file_path: str, new_agent_id: str | None = None) -> dict[str, Any]:
        """Import profile from JSON file."""
        from mindbot.memory.migration import ImportOptions, MemoryImporter

        importer = MemoryImporter(
            index_store=self._index_store,
            content_store=self._content_store,
            vector_store=self._vector_store,
        )
        options = ImportOptions(new_agent_id=new_agent_id)
        return importer.import_from_file(file_path, options=options)