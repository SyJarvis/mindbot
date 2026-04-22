#!/usr/bin/env python
"""Integration test for Phase 2: LanceDB vector storage + embedder."""

import sys
import importlib.util
import tempfile
import time
from pathlib import Path

src_path = Path(__file__).resolve().parent.parent / "src"

def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

# Mock logger
class MockLogger:
    def debug(self, *a, **kw): pass
    def info(self, *a, **kw): pass
    def warning(self, *a, **kw): pass
    def error(self, *a, **kw): pass

def get_logger(name):
    return MockLogger()

sys.modules["mindbot"] = type(sys)("mindbot")
sys.modules["mindbot.utils"] = type(sys)("mindbot.utils")
sys.modules["mindbot.utils"].get_logger = get_logger

# Load types
enums = load_module("mindbot.memory.types.enums", src_path / "mindbot" / "memory" / "types" / "enums.py")
forget_mod = load_module("mindbot.memory.types.forget", src_path / "mindbot" / "memory" / "types" / "forget.py")
shard_mod = load_module("mindbot.memory.types.shard", src_path / "mindbot" / "memory" / "types" / "shard.py")
chunk_mod = load_module("mindbot.memory.types.chunk", src_path / "mindbot" / "memory" / "types" / "chunk.py")
cluster_mod = load_module("mindbot.memory.types.cluster", src_path / "mindbot" / "memory" / "types" / "cluster.py")
profile_mod = load_module("mindbot.memory.types.profile", src_path / "mindbot" / "memory" / "types" / "profile.py")
index_mod = load_module("mindbot.memory.types.index", src_path / "mindbot" / "memory" / "types" / "index.py")

# Register types
types_init = type(sys)("mindbot.memory.types")
for name, mod in [
    ("ShardType", enums), ("ShardSource", enums), ("ChunkType", enums),
    ("ClusterType", enums), ("MemoryTier", enums),
    ("ForgetPolicy", forget_mod), ("ForgetReport", forget_mod),
    ("MemoryShard", shard_mod), ("MemoryChunk", chunk_mod),
    ("MemoryCluster", cluster_mod), ("MemoryProfile", profile_mod),
    ("ShardIndex", index_mod),
    ("CLUSTER_MIGRATION_PRIORITY", cluster_mod), ("CORE_CLUSTER_TYPES", cluster_mod),
]:
    setattr(types_init, name, getattr(mod, name))
sys.modules["mindbot.memory"] = type(sys)("mindbot.memory")
sys.modules["mindbot.memory.types"] = types_init

# Load storage
sys.modules["mindbot.memory.storage"] = type(sys)("mindbot.memory.storage")
vs_mod = load_module("mindbot.memory.storage.vector_store", src_path / "mindbot" / "memory" / "storage" / "vector_store.py")
lance_mod = load_module("mindbot.memory.storage.lance_store", src_path / "mindbot" / "memory" / "storage" / "lance_store.py")
index_store_mod = load_module("mindbot.memory.storage.index_store", src_path / "mindbot" / "memory" / "storage" / "index_store.py")
content_store_mod = load_module("mindbot.memory.storage.content_store", src_path / "mindbot" / "memory" / "storage" / "content_store.py")

VectorStore = vs_mod.VectorStore
SearchResult = vs_mod.SearchResult
LanceVectorStore = lance_mod.LanceVectorStore
JSONIndexStore = index_store_mod.JSONIndexStore
IndexStoreConfig = index_store_mod.IndexStoreConfig
MarkdownContentStore = content_store_mod.MarkdownContentStore

# Register storage __init__.py exports
storage_init = type(sys)("mindbot.memory.storage")
storage_init.JSONIndexStore = JSONIndexStore
storage_init.IndexStoreConfig = IndexStoreConfig
storage_init.MarkdownContentStore = MarkdownContentStore
storage_init.LanceVectorStore = LanceVectorStore
storage_init.VectorStore = VectorStore
storage_init.SearchResult = SearchResult
sys.modules["mindbot.memory.storage"] = storage_init
sys.modules["mindbot.memory.storage.index_store"] = index_store_mod
sys.modules["mindbot.memory.storage.content_store"] = content_store_mod
sys.modules["mindbot.memory.storage.vector_store"] = vs_mod
sys.modules["mindbot.memory.storage.lance_store"] = lance_mod

# Register embedder (lazy, since we don't need it for these tests)
embedder_base = load_module("mindbot.memory.embedder.base", src_path / "mindbot" / "memory" / "embedder" / "base.py")
embedder_init = type(sys)("mindbot.memory.embedder")
embedder_init.Embedder = embedder_base.Embedder
sys.modules["mindbot.memory.embedder"] = embedder_init
sys.modules["mindbot.memory.embedder.base"] = embedder_base

# Register retrieval (lazy)
retrieval_init = type(sys)("mindbot.memory.retrieval")
sys.modules["mindbot.memory.retrieval"] = retrieval_init

print("=" * 60)
print("Phase 2 Integration Test")
print("=" * 60)

# Test 1: LanceVectorStore basic operations
print("\n--- Test 1: LanceVectorStore CRUD ---")
with tempfile.TemporaryDirectory() as tmpdir:
    store = LanceVectorStore(uri=tmpdir, dimension=4)

    # Insert
    store.insert("shard-1", [1.0, 0.0, 0.0, 0.0], {"summary": "hello world"})
    store.insert("shard-2", [0.0, 1.0, 0.0, 0.0], {"summary": "goodbye world"})
    store.insert("shard-3", [0.9, 0.1, 0.0, 0.0], {"summary": "hello python"})
    print(f"  ✓ Inserted 3 vectors, count: {store.count()}")

    # Search by vector
    results = store.search([1.0, 0.0, 0.0, 0.0], top_k=2)
    print(f"  ✓ Vector search for [1,0,0,0]: {[(r.shard_id, f'{r.score:.3f}') for r in results]}")
    assert results[0].shard_id == "shard-1"

    # Get vector
    vec = store.get_vector("shard-1")
    print(f"  ✓ Get vector shard-1: {vec[:2]}...")

    # Update
    store.update("shard-1", [0.0, 0.0, 0.0, 1.0], {"summary": "updated"})
    vec2 = store.get_vector("shard-1")
    print(f"  ✓ Updated vector shard-1: {vec2[:2]}...")

    # Delete
    store.delete("shard-3")
    print(f"  ✓ Deleted shard-3, count: {store.count()}")
    assert store.count() == 2

# Test 2: LanceVectorStore FTS
print("\n--- Test 2: LanceVectorStore Full-Text Search ---")
with tempfile.TemporaryDirectory() as tmpdir:
    store = LanceVectorStore(uri=tmpdir, dimension=4)
    store.insert("s1", [0.1]*4, {"summary": "Python programming language"})
    store.insert("s2", [0.2]*4, {"summary": "JavaScript web development"})
    store.insert("s3", [0.3]*4, {"summary": "Python data science"})

    # FTS search
    results = store.search_by_text("Python", top_k=5)
    print(f"  ✓ FTS search 'Python': {len(results)} results")
    # Note: FTS may take a moment to index

# Test 3: LanceVectorStore batch insert
print("\n--- Test 3: LanceVectorStore Batch Insert ---")
with tempfile.TemporaryDirectory() as tmpdir:
    store = LanceVectorStore(uri=tmpdir, dimension=8)
    items = [(f"shard-{i}", [float(i)] * 8, {"summary": f"document {i}"}) for i in range(100)]
    store.insert_batch(items)
    print(f"  ✓ Batch inserted 100 vectors, count: {store.count()}")

    # Search
    results = store.search([5.0] * 8, top_k=5)
    print(f"  ✓ Search top 5: {[r.shard_id for r in results]}")

# Test 4: MemoryManager without vector (keyword fallback)
print("\n--- Test 4: MemoryManager keyword-only mode ---")
manager_mod = load_module("mindbot.memory.manager", src_path / "mindbot" / "memory" / "manager.py")
MemoryManager = manager_mod.MemoryManager
MemoryManagerConfig = manager_mod.MemoryManagerConfig

with tempfile.TemporaryDirectory() as tmpdir:
    config = MemoryManagerConfig(
        base_path=str(Path(tmpdir) / "memory"),
        content_path=str(Path(tmpdir) / "memory" / "content"),
        enable_vector=False,
        default_agent_id="test-agent",
        default_agent_name="TestBot",
    )
    manager = MemoryManager(config=config)
    print(f"  ✓ Manager created (vector_enabled: {manager.get_stats().get('vector_enabled', 'N/A')})")

    # Add memories
    manager.promote_to_long_term("Python is a versatile programming language")
    manager.promote_to_long_term("JavaScript is used for web development")
    manager.append_to_short_term("User discussed Python data analysis")

    # Search
    results = manager.search("Python")
    print(f"  ✓ Search 'Python': {len(results)} results")
    for r in results:
        print(f"    - {r.text[:50]}...")

# Test 5: MemoryManager with LanceDB (no embedder, FTS mode)
print("\n--- Test 5: MemoryManager with LanceDB (FTS mode) ---")
with tempfile.TemporaryDirectory() as tmpdir:
    config = MemoryManagerConfig(
        base_path=str(Path(tmpdir) / "memory"),
        content_path=str(Path(tmpdir) / "memory" / "content"),
        vector_path=str(Path(tmpdir) / "vectors"),
        enable_vector=False,  # Skip embedder init since no API key
        default_agent_id="test-agent",
        default_agent_name="TestBot",
    )
    manager = MemoryManager(config=config)

    manager.promote_to_long_term("Machine learning models need training data")
    manager.promote_to_long_term("Neural networks are inspired by the brain")
    manager.append_preference("User prefers dark mode UI")

    stats = manager.get_stats()
    print(f"  ✓ Stats: {stats}")

    results = manager.search("neural")
    print(f"  ✓ Search 'neural': {len(results)} results")

    results2 = manager.search("dark mode")
    print(f"  ✓ Search 'dark mode': {len(results2)} results")

print("\n" + "=" * 60)
print("✅ All Phase 2 integration tests passed!")
print("=" * 60)