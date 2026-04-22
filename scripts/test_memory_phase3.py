#!/usr/bin/env python
"""Integration test for Phase 3: Update mechanism and summarizer."""

import sys, importlib.util, tempfile, time
from pathlib import Path
from typing import Any

src_path = Path(__file__).resolve().parent.parent / "src"

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

class MockLogger:
    def debug(self, *a, **kw): pass
    def info(self, *a, **kw): pass
    def warning(self, *a, **kw): pass
    def error(self, *a, **kw): pass
def get_logger(name): return MockLogger()

sys.modules["mindbot"] = type(sys)("mindbot")
sys.modules["mindbot.utils"] = type(sys)("mindbot.utils")
sys.modules["mindbot.utils"].get_logger = get_logger
sys.modules["mindbot.memory"] = type(sys)("mindbot.memory")

# Types
enums = load_module("mindbot.memory.types.enums", src_path / "mindbot" / "memory" / "types" / "enums.py")
forget_mod = load_module("mindbot.memory.types.forget", src_path / "mindbot" / "memory" / "types" / "forget.py")
shard_mod = load_module("mindbot.memory.types.shard", src_path / "mindbot" / "memory" / "types" / "shard.py")
chunk_mod = load_module("mindbot.memory.types.chunk", src_path / "mindbot" / "memory" / "types" / "chunk.py")
cluster_mod = load_module("mindbot.memory.types.cluster", src_path / "mindbot" / "memory" / "types" / "cluster.py")
profile_mod = load_module("mindbot.memory.types.profile", src_path / "mindbot" / "memory" / "types" / "profile.py")
index_mod = load_module("mindbot.memory.types.index", src_path / "mindbot" / "memory" / "types" / "index.py")

types_init = type(sys)("mindbot.memory.types")
for name, mod in [("ShardType", enums), ("ShardSource", enums), ("ChunkType", enums),
    ("ClusterType", enums), ("MemoryTier", enums), ("ForgetPolicy", forget_mod),
    ("ForgetReport", forget_mod), ("MemoryShard", shard_mod), ("MemoryChunk", chunk_mod),
    ("MemoryCluster", cluster_mod), ("MemoryProfile", profile_mod), ("ShardIndex", index_mod),
    ("CLUSTER_MIGRATION_PRIORITY", cluster_mod), ("CORE_CLUSTER_TYPES", cluster_mod)]:
    setattr(types_init, name, getattr(mod, name))
sys.modules["mindbot.memory.types"] = types_init

# Storage
vs_mod = load_module("mindbot.memory.storage.vector_store", src_path / "mindbot" / "memory" / "storage" / "vector_store.py")
index_store_mod = load_module("mindbot.memory.storage.index_store", src_path / "mindbot" / "memory" / "storage" / "index_store.py")
content_store_mod = load_module("mindbot.memory.storage.content_store", src_path / "mindbot" / "memory" / "storage" / "content_store.py")

# Register storage with all exports BEFORE loading modules that import from it
storage_init = type(sys)("mindbot.memory.storage")
storage_init.VectorStore = vs_mod.VectorStore
storage_init.SearchResult = vs_mod.SearchResult
storage_init.JSONIndexStore = index_store_mod.JSONIndexStore
storage_init.IndexStoreConfig = index_store_mod.IndexStoreConfig
storage_init.MarkdownContentStore = content_store_mod.MarkdownContentStore
storage_init.__all__ = ["JSONIndexStore", "IndexStoreConfig", "MarkdownContentStore", "LanceVectorStore", "VectorStore", "SearchResult"]
storage_init.__path__ = [str(src_path / "mindbot" / "memory" / "storage")]
sys.modules["mindbot.memory.storage"] = storage_init
sys.modules["mindbot.memory.storage.index_store"] = index_store_mod
sys.modules["mindbot.memory.storage.content_store"] = content_store_mod
sys.modules["mindbot.memory.storage.vector_store"] = vs_mod

# Register lifecycle modules needed by manager.py
summarizer_mod = load_module("mindbot.memory.lifecycle.summarizer", src_path / "mindbot" / "memory" / "lifecycle" / "summarizer.py")
updater_mod2 = load_module("mindbot.memory.lifecycle.updater", src_path / "mindbot" / "memory" / "lifecycle" / "updater.py")
lifecycle_init = type(sys)("mindbot.memory.lifecycle")
lifecycle_init.SummaryGenerator = summarizer_mod.SummaryGenerator
lifecycle_init.MemoryUpdater = updater_mod2.MemoryUpdater
lifecycle_init.UpdateResult = updater_mod2.UpdateResult
sys.modules["mindbot.memory.lifecycle"] = lifecycle_init
sys.modules["mindbot.memory.lifecycle.summarizer"] = summarizer_mod
sys.modules["mindbot.memory.lifecycle.updater"] = updater_mod2

# Now load manager
manager_mod = load_module("mindbot.memory.manager", src_path / "mindbot" / "memory" / "manager.py")
MemoryManager = manager_mod.MemoryManager
MemoryManagerConfig = manager_mod.MemoryManagerConfig

# Embedder stub
embedder_base = load_module("mindbot.memory.embedder.base", src_path / "mindbot" / "memory" / "embedder" / "base.py")
embedder_init = type(sys)("mindbot.memory.embedder")
embedder_init.Embedder = embedder_base.Embedder
sys.modules["mindbot.memory.embedder"] = embedder_init
sys.modules["mindbot.memory.embedder.base"] = embedder_base
sys.modules["mindbot.memory.retrieval"] = type(sys)("mindbot.memory.retrieval")

ShardType = enums.ShardType
ShardSource = enums.ShardSource
ShardIndex = index_mod.ShardIndex

print("=" * 60)
print("Phase 3 Integration Test: Update Mechanism")
print("=" * 60)

# Test 1: SummaryGenerator
print("\n--- Test 1: SummaryGenerator ---")
summarizer_mod = load_module("mindbot.memory.lifecycle.summarizer", src_path / "mindbot" / "memory" / "lifecycle" / "summarizer.py")
Summarizer = summarizer_mod.SummaryGenerator
gen = Summarizer()

summary = gen.generate_summary("Python is a versatile programming language used for web development and data science")
print(f"  ✓ Summary: '{summary}'")
assert len(summary) <= 103

kw = gen.extract_keywords("Python machine learning data analysis numpy pandas")
print(f"  ✓ Keywords: {kw}")

idx_data = gen.generate_index_data("User prefers dark mode for coding")
print(f"  ✓ Index data: summary='{idx_data['summary']}', keywords={idx_data['keywords']}, hash={idx_data['content_hash']}")

# Test 2: MemoryUpdater - exact duplicate detection
print("\n--- Test 2: Exact Duplicate Detection ---")
updater_mod = load_module("mindbot.memory.lifecycle.updater", src_path / "mindbot" / "memory" / "lifecycle" / "updater.py")
Updater = updater_mod.MemoryUpdater

with tempfile.TemporaryDirectory() as tmpdir:
    from mindbot.memory.storage.index_store import JSONIndexStore, IndexStoreConfig
    from mindbot.memory.storage.content_store import MarkdownContentStore

    index_store = JSONIndexStore(config=IndexStoreConfig(base_path=str(Path(tmpdir) / "idx")))
    content_store = MarkdownContentStore(base_path=str(Path(tmpdir) / "content"))
    updater = Updater(index_store=index_store, content_store=content_store)

    # Store a memory first
    idx = ShardIndex.create(shard_id="shard-1", markdown_path="shards/shard-1.md", summary="Python programming")
    idx.metadata["content_hash"] = "abc123"
    index_store.update_shard_index("shard-1", idx)
    content_store.write_shard("shard-1", "Python programming language")

    # Try same hash → ignore
    result = updater._find_by_hash("abc123")
    print(f"  ✓ Found by hash: {result}")
    assert result == "shard-1"

    # Non-existent hash
    result2 = updater._find_by_hash("xyz789")
    print(f"  ✓ Not found by hash: {result2}")
    assert result2 == ""

# Test 3: MemoryUpdater - merge detection
print("\n--- Test 3: Merge Decision ---")
with tempfile.TemporaryDirectory() as tmpdir:
    index_store = JSONIndexStore(config=IndexStoreConfig(base_path=str(Path(tmpdir) / "idx")))
    content_store = MarkdownContentStore(base_path=str(Path(tmpdir) / "content"))

    # Create existing shard
    existing_text = "User likes Python for data analysis"
    idx = ShardIndex.create(shard_id="shard-1", markdown_path="shards/shard-1.md", summary=existing_text)
    idx.metadata["content_hash"] = "hash1"
    index_store.update_shard_index("shard-1", idx)
    content_store.write_shard("shard-1", existing_text)

    updater = Updater(index_store=index_store, content_store=content_store)

    # Test store_new (completely different)
    result = updater.process("Weather is sunny today", ShardType.FACT)
    print(f"  ✓ Completely different → action: {result.action}")
    assert result.action == "store_new"

    # Test merge (very similar)
    result = updater.process("User also likes R for statistics", ShardType.FACT)
    print(f"  ✓ Partially different → action: {result.action}")

# Test 4: MemoryUpdater - contradiction detection
print("\n--- Test 4: Contradiction Detection ---")
with tempfile.TemporaryDirectory() as tmpdir:
    index_store = JSONIndexStore(config=IndexStoreConfig(base_path=str(Path(tmpdir) / "idx")))
    content_store = MarkdownContentStore(base_path=str(Path(tmpdir) / "content"))

    updater = Updater(index_store=index_store, content_store=content_store)

    # Test contradiction heuristics
    assert updater._is_contradictory("I like Python", "I do not like Python") == True
    print("  ✓ 'like' vs 'do not like' → contradictory")

    assert updater._is_contradictory("Python is great", "Python is awesome") == False
    print("  ✓ 'great' vs 'awesome' → not contradictory")

    assert updater._is_contradictory("User prefers dark mode", "User prefers light mode") == True
    print("  ✓ 'dark mode' vs 'light mode' → contradictory")

# Test 5: Full MemoryManager integration with updater
print("\n--- Test 5: MemoryManager with Update Logic ---")

with tempfile.TemporaryDirectory() as tmpdir:
    config = MemoryManagerConfig(
        base_path=str(Path(tmpdir) / "memory"),
        content_path=str(Path(tmpdir) / "memory" / "content"),
        enable_vector=False,
        default_agent_id="test-agent",
        default_agent_name="TestBot",
    )
    manager = MemoryManager(config=config)

    # First write
    shards1 = manager.promote_to_long_term("Python is a great language for data science")
    print(f"  ✓ First write: {shards1[0].id[:8]}")

    # Different content → new shard
    shards2 = manager.promote_to_long_term("JavaScript is used for web development")
    stats = manager.get_stats()
    print(f"  ✓ After 2 writes: {stats['shards']} shards")

    # Exact same content → should be ignored (hash dedup)
    shards3 = manager.promote_to_long_term("Python is a great language for data science")
    stats_after = manager.get_stats()
    print(f"  ✓ After duplicate: {stats_after['shards']} shards (should be same)")
    assert stats_after["shards"] == stats["shards"], "Duplicate should be ignored"

    # Verify search still works
    results = manager.search("Python")
    print(f"  ✓ Search 'Python': {len(results)} results")

print("\n" + "=" * 60)
print("✅ All Phase 3 integration tests passed!")
print("=" * 60)
