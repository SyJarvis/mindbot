#!/usr/bin/env python
"""Direct test script for memory module (using importlib to bypass package init)."""

import sys
import importlib.util
import tempfile
from pathlib import Path

# Load memory modules directly without triggering mindbot.__init__
src_path = Path(__file__).resolve().parent.parent / "src"

def load_module(name: str, path: Path):
    """Load a module directly from file path."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

# Create a minimal mock for mindbot.utils
class MockLogger:
    def debug(self, *args): pass
    def info(self, *args): pass
    def warning(self, *args): pass
    def error(self, *args): pass

def get_logger(name):
    return MockLogger()

sys.modules["mindbot"] = type(sys)("mindbot")
sys.modules["mindbot.utils"] = type(sys)("mindbot.utils")
sys.modules["mindbot.utils"].get_logger = get_logger

# Load types modules in dependency order
enums = load_module("mindbot.memory.types.enums", src_path / "mindbot" / "memory" / "types" / "enums.py")
# Register the types package
sys.modules["mindbot.memory"] = type(sys)("mindbot.memory")
sys.modules["mindbot.memory.types"] = type(sys)("mindbot.memory.types")
sys.modules["mindbot.memory.types.enums"] = enums

forget_mod = load_module("mindbot.memory.types.forget", src_path / "mindbot" / "memory" / "types" / "forget.py")
sys.modules["mindbot.memory.types.forget"] = forget_mod

shard_mod = load_module("mindbot.memory.types.shard", src_path / "mindbot" / "memory" / "types" / "shard.py")
sys.modules["mindbot.memory.types.shard"] = shard_mod

chunk_mod = load_module("mindbot.memory.types.chunk", src_path / "mindbot" / "memory" / "types" / "chunk.py")
sys.modules["mindbot.memory.types.chunk"] = chunk_mod

cluster_mod = load_module("mindbot.memory.types.cluster", src_path / "mindbot" / "memory" / "types" / "cluster.py")
sys.modules["mindbot.memory.types.cluster"] = cluster_mod

profile_mod = load_module("mindbot.memory.types.profile", src_path / "mindbot" / "memory" / "types" / "profile.py")
sys.modules["mindbot.memory.types.profile"] = profile_mod

index_mod = load_module("mindbot.memory.types.index", src_path / "mindbot" / "memory" / "types" / "index.py")
sys.modules["mindbot.memory.types.index"] = index_mod

# Also register the types __init__.py exports
types_init = type(sys)("mindbot.memory.types")
# Add all exports
types_init.ChunkType = enums.ChunkType
types_init.ClusterType = enums.ClusterType
types_init.MemoryTier = enums.MemoryTier
types_init.ShardSource = enums.ShardSource
types_init.ShardType = enums.ShardType
types_init.ForgetPolicy = forget_mod.ForgetPolicy
types_init.ForgetReport = forget_mod.ForgetReport
types_init.MemoryShard = shard_mod.MemoryShard
types_init.MemoryChunk = chunk_mod.MemoryChunk
types_init.MemoryCluster = cluster_mod.MemoryCluster
types_init.CLUSTER_MIGRATION_PRIORITY = cluster_mod.CLUSTER_MIGRATION_PRIORITY
types_init.CORE_CLUSTER_TYPES = cluster_mod.CORE_CLUSTER_TYPES
types_init.MemoryProfile = profile_mod.MemoryProfile
types_init.ShardIndex = index_mod.ShardIndex
types_init.__all__ = [
    "ShardType", "ShardSource", "ChunkType", "ClusterType", "MemoryTier",
    "MemoryShard", "MemoryChunk", "MemoryCluster", "MemoryProfile", "ShardIndex",
    "ForgetPolicy", "ForgetReport", "CLUSTER_MIGRATION_PRIORITY", "CORE_CLUSTER_TYPES",
]
sys.modules["mindbot.memory.types"] = types_init

ShardType = enums.ShardType
ClusterType = enums.ClusterType
ChunkType = enums.ChunkType
ShardSource = enums.ShardSource
MemoryShard = shard_mod.MemoryShard
MemoryChunk = chunk_mod.MemoryChunk
MemoryCluster = cluster_mod.MemoryCluster
MemoryProfile = profile_mod.MemoryProfile
ShardIndex = index_mod.ShardIndex
ForgetPolicy = forget_mod.ForgetPolicy

print("✓ Enums imported:", ShardType.FACT, ClusterType.IDENTITY)

shard = MemoryShard.create(text="Test memory content")
print("✓ MemoryShard.create:", shard.id[:8], shard.shard_type)

chunk = MemoryChunk.create(name="TestChunk", cluster_id="cluster-001")
print("✓ MemoryChunk.create:", chunk.id[:8], chunk.name)

cluster = MemoryCluster.create(
    name="Identity",
    cluster_type=ClusterType.IDENTITY,
    profile_id="profile-001",
)
print("✓ MemoryCluster.create:", cluster.id[:8], "priority:", cluster.migration_priority)

profile = MemoryProfile.create(agent_id="test-001", agent_name="TestBot")
print("✓ MemoryProfile.create:", profile.agent_id, profile.agent_name)

index = ShardIndex.create(
    shard_id="shard-001",
    markdown_path="shards/shard-001.md",
    summary="Test summary",
    shard_type=ShardType.FACT,
)
print("✓ ShardIndex.create:", index.shard_id, index.summary)

policy = ForgetPolicy()
print("✓ ForgetPolicy:", policy.forget_threshold, policy.delete_threshold)

# Test storage layer
# Register storage package
sys.modules["mindbot.memory.storage"] = type(sys)("mindbot.memory.storage")

index_store_mod = load_module("mindbot.memory.storage.index_store", src_path / "mindbot" / "memory" / "storage" / "index_store.py")
sys.modules["mindbot.memory.storage.index_store"] = index_store_mod
sys.modules["mindbot.memory.storage"].JSONIndexStore = index_store_mod.JSONIndexStore
sys.modules["mindbot.memory.storage"].IndexStoreConfig = index_store_mod.IndexStoreConfig

content_store_mod = load_module("mindbot.memory.storage.content_store", src_path / "mindbot" / "memory" / "storage" / "content_store.py")
sys.modules["mindbot.memory.storage.content_store"] = content_store_mod
sys.modules["mindbot.memory.storage"].MarkdownContentStore = content_store_mod.MarkdownContentStore
sys.modules["mindbot.memory.storage"].__all__ = ["JSONIndexStore", "IndexStoreConfig", "MarkdownContentStore"]

JSONIndexStore = index_store_mod.JSONIndexStore
IndexStoreConfig = index_store_mod.IndexStoreConfig
MarkdownContentStore = content_store_mod.MarkdownContentStore

with tempfile.TemporaryDirectory() as tmpdir:
    config = IndexStoreConfig(base_path=tmpdir)
    store = JSONIndexStore(config=config)
    print("✓ JSONIndexStore created")

    profile = store.ensure_default_structure("test-agent", "TestBot")
    print("✓ Default structure:", profile.agent_id, "clusters:", len(profile.cluster_ids))

    # Test shard index
    idx = ShardIndex.create(
        shard_id="test-shard",
        markdown_path="test.md",
        summary="Test",
    )
    store.update_shard_index("test-shard", idx)
    loaded = store.get_shard_index("test-shard")
    print("✓ Shard index saved/loaded:", loaded.summary)

    stats = store.get_stats()
    print("✓ Stats:", stats)

with tempfile.TemporaryDirectory() as tmpdir:
    content_store = MarkdownContentStore(base_path=tmpdir)
    print("✓ MarkdownContentStore created")

    # Write and read
    content_store.write_shard("shard-001", "This is test content.", {"type": "test"})
    read = content_store.read_shard("shard-001")
    print("✓ Content read:", read[:20] + "...")

    # Search
    matches = content_store.search_by_keyword("test")
    print("✓ Keyword search:", matches)

    stats = content_store.get_stats()
    print("✓ Content stats:", stats)

# Test MemoryManager
manager_mod = load_module("mindbot.memory.manager", src_path / "mindbot" / "memory" / "manager.py")
MemoryManager = manager_mod.MemoryManager
MemoryManagerConfig = manager_mod.MemoryManagerConfig

with tempfile.TemporaryDirectory() as tmpdir:
    config = MemoryManagerConfig(
        base_path=str(Path(tmpdir) / "memory"),
        content_path=str(Path(tmpdir) / "memory" / "content"),
        default_agent_id="test-agent",
        default_agent_name="TestBot",
    )
    manager = MemoryManager(config=config)
    print("✓ MemoryManager created")

    # Test write
    shards = manager.append_to_short_term("User asked about Python")
    print("✓ append_to_short_term:", shards[0].id[:8])

    # Test search
    results = manager.search("Python")
    print("✓ search returned:", len(results), "results")

    # Test stats
    stats = manager.get_stats()
    print("✓ Manager stats:", stats)

print("\n✅ All memory module tests passed!")