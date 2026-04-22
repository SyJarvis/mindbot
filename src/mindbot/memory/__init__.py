"""Memory subsystem with four-tier structure."""

# Core manager
from mindbot.memory.manager import MemoryManager, MemoryManagerConfig

# Storage layer
from mindbot.memory.storage import (
    IndexStoreConfig,
    JSONIndexStore,
    LanceVectorStore,
    MarkdownContentStore,
    SearchResult,
    VectorStore,
)

# Migration
from mindbot.memory.migration import (
    ExportOptions,
    ImportOptions,
    LegacyMigrator,
    MemoryExporter,
    MemoryImporter,
    MigrationPackage,
)

# Data types
from mindbot.memory.types import (
    ChunkType,
    ClusterType,
    ForgetPolicy,
    ForgetReport,
    MemoryChunk,
    MemoryCluster,
    MemoryProfile,
    MemoryShard,
    MemoryTier,
    ShardIndex,
    ShardSource,
    ShardType,
)

__all__ = [
    # Manager
    "MemoryManager",
    "MemoryManagerConfig",
    # Storage
    "JSONIndexStore",
    "IndexStoreConfig",
    "MarkdownContentStore",
    "LanceVectorStore",
    "VectorStore",
    "SearchResult",
    # Embedder
    "Embedder",
    "OpenAIEmbedder",
    # Retrieval
    "HybridRetriever",
    # Data types
    "MemoryShard",
    "MemoryChunk",
    "MemoryCluster",
    "MemoryProfile",
    "ShardIndex",
    "ForgetPolicy",
    "ForgetReport",
    # Enums
    "ShardType",
    "ShardSource",
    "ChunkType",
    "ClusterType",
    "MemoryTier",
    # Migration
    "ExportOptions",
    "ImportOptions",
    "LegacyMigrator",
    "MemoryExporter",
    "MemoryImporter",
    "MigrationPackage",
]
