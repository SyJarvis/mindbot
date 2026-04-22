#!/usr/bin/env python
"""Integration test for Phase 4: Forget and Promotion mechanisms."""

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
    def info(self, *a, **kw): print(f"[INFO] {a}")
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

ShardType = enums.ShardType
ShardSource = enums.ShardSource
ShardIndex = index_mod.ShardIndex
ForgetPolicy = forget_mod.ForgetPolicy
ClusterType = enums.ClusterType

# Storage
vs_mod = load_module("mindbot.memory.storage.vector_store", src_path / "mindbot" / "memory" / "storage" / "vector_store.py")
index_store_mod = load_module("mindbot.memory.storage.index_store", src_path / "mindbot" / "memory" / "storage" / "index_store.py")
content_store_mod = load_module("mindbot.memory.storage.content_store", src_path / "mindbot" / "memory" / "storage" / "content_store.py")

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

# Lifecycle
summarizer_mod = load_module("mindbot.memory.lifecycle.summarizer", src_path / "mindbot" / "memory" / "lifecycle" / "summarizer.py")
updater_mod2 = load_module("mindbot.memory.lifecycle.updater", src_path / "mindbot" / "memory" / "lifecycle" / "updater.py")
forgetter_mod = load_module("mindbot.memory.lifecycle.forgetter", src_path / "mindbot" / "memory" / "lifecycle" / "forgetter.py")
promoter_mod = load_module("mindbot.memory.lifecycle.promoter", src_path / "mindbot" / "memory" / "lifecycle" / "promoter.py")

lifecycle_init = type(sys)("mindbot.memory.lifecycle")
lifecycle_init.SummaryGenerator = summarizer_mod.SummaryGenerator
lifecycle_init.MemoryUpdater = updater_mod2.MemoryUpdater
lifecycle_init.UpdateResult = updater_mod2.UpdateResult
lifecycle_init.MemoryForgetter = forgetter_mod.MemoryForgetter
lifecycle_init.MemoryPromoter = promoter_mod.MemoryPromoter
sys.modules["mindbot.memory.lifecycle"] = lifecycle_init
sys.modules["mindbot.memory.lifecycle.summarizer"] = summarizer_mod
sys.modules["mindbot.memory.lifecycle.updater"] = updater_mod2
sys.modules["mindbot.memory.lifecycle.forgetter"] = forgetter_mod
sys.modules["mindbot.memory.lifecycle.promoter"] = promoter_mod

# Embedder stub
embedder_base = load_module("mindbot.memory.embedder.base", src_path / "mindbot" / "memory" / "embedder" / "base.py")
embedder_init = type(sys)("mindbot.memory.embedder")
embedder_init.Embedder = embedder_base.Embedder
sys.modules["mindbot.memory.embedder"] = embedder_init
sys.modules["mindbot.memory.embedder.base"] = embedder_base
sys.modules["mindbot.memory.retrieval"] = type(sys)("mindbot.memory.retrieval")

# Manager
manager_mod = load_module("mindbot.memory.manager", src_path / "mindbot" / "memory" / "manager.py")
MemoryManager = manager_mod.MemoryManager
MemoryManagerConfig = manager_mod.MemoryManagerConfig

print("=" * 60)
print("Phase 4 Integration Test: Forget & Promotion")
print("=" * 60)

# Test 1: ForgetPolicy configuration
print("\n--- Test 1: ForgetPolicy ---")
policy = ForgetPolicy()
print(f"  ✓ Access weight: {policy.access_weight}")
print(f"  ✓ Thresholds: forget={policy.forget_threshold}, archive={policy.archive_threshold}, delete={policy.delete_threshold}")
print(f"  ✓ Protection days: {policy.recent_protection_days}")
assert policy.access_weight + policy.age_weight + policy.redundancy_weight + policy.density_weight + policy.source_weight == 1.0

# Test 2: MemoryForgetter scoring
print("\n--- Test 2: MemoryForgetter Scoring ---")
with tempfile.TemporaryDirectory() as tmpdir:
    from mindbot.memory.storage.index_store import JSONIndexStore, IndexStoreConfig
    from mindbot.memory.storage.content_store import MarkdownContentStore
    from mindbot.memory.lifecycle.forgetter import MemoryForgetter

    index_store = JSONIndexStore(config=IndexStoreConfig(base_path=str(Path(tmpdir) / "idx")))
    content_store = MarkdownContentStore(base_path=str(Path(tmpdir) / "content"))
    forgetter = MemoryForgetter(index_store=index_store, content_store=content_store, policy=policy)
    forgetter.set_total_queries(100)

    # Create test shards
    idx1 = ShardIndex.create(shard_id="high-access", markdown_path="a.md", summary="Important fact")
    idx1.access_count = 20
    idx1.created_at = time.time() - 86400 * 5  # 5 days old
    index_store.update_shard_index("high-access", idx1)

    idx2 = ShardIndex.create(shard_id="low-access", markdown_path="b.md", summary="Trivial note")
    idx2.access_count = 0
    idx2.created_at = time.time() - 86400 * 30  # 30 days old
    idx2.source = ShardSource.EXTRACT
    index_store.update_shard_index("low-access", idx2)

    # Score high-access (should be low forget score)
    score1 = forgetter.compute_forget_score(idx1)
    print(f"  ✓ High-access shard score: {score1:.3f} (should be low)")

    # Score low-access (should be high forget score)
    score2 = forgetter.compute_forget_score(idx2)
    print(f"  ✓ Low-access shard score: {score2:.3f} (should be high)")

    assert score1 < score2, "High-access should have lower forget score"

# Test 3: MemoryPromoter scoring
print("\n--- Test 3: MemoryPromoter Scoring ---")
from mindbot.memory.lifecycle.promoter import MemoryPromoter

with tempfile.TemporaryDirectory() as tmpdir:
    index_store = JSONIndexStore(config=IndexStoreConfig(base_path=str(Path(tmpdir) / "idx")))
    content_store = MarkdownContentStore(base_path=str(Path(tmpdir) / "content"))
    index_store.ensure_default_structure("test-agent", "TestBot")
    promoter = MemoryPromoter(index_store=index_store, content_store=content_store)

    # Create promotion candidate
    idx = ShardIndex.create(shard_id="promote-me", markdown_path="x.md", summary="Important preference")
    idx.access_count = 10
    idx.created_at = time.time() - 86400 * 7  # 7 days old
    idx.shard_type = ShardType.PREFERENCE
    idx.is_permanent = True
    index_store.update_shard_index("promote-me", idx)

    score = promoter.compute_promotion_score(idx)
    print(f"  ✓ Promotion candidate score: {score:.3f} (should be >= threshold)")
    assert score >= 0.7

# Test 4: Full forget cycle via MemoryManager
print("\n--- Test 4: MemoryManager Forget Cycle ---")
with tempfile.TemporaryDirectory() as tmpdir:
    config = MemoryManagerConfig(
        base_path=str(Path(tmpdir) / "memory"),
        content_path=str(Path(tmpdir) / "memory" / "content"),
        enable_vector=False,
        default_agent_id="test-agent",
        default_agent_name="TestBot",
    )
    manager = MemoryManager(config=config)

    # Add some memories
    manager.promote_to_long_term("Important knowledge about Python")
    manager.append_to_short_term("Temporary dialogue message")
    manager.append_preference("User preference for dark mode")

    stats_before = manager.get_stats()
    print(f"  ✓ Before forget: {stats_before['shards']} shards")

    # Run forget (recent memories should be protected)
    report = manager.run_forget_cycle()
    print(f"  ✓ Forget report: deleted={len(report.deleted)}, archived={len(report.archived)}, kept={len(report.kept)}")

    stats_after = manager.get_stats()
    print(f"  ✓ After forget: {stats_after['shards']} shards")

    # Recent memories should be kept (protection)
    assert len(report.deleted) == 0, "Recent memories should be protected"

# Test 5: Promotion cycle
print("\n--- Test 5: MemoryManager Promotion Cycle ---")
with tempfile.TemporaryDirectory() as tmpdir:
    config = MemoryManagerConfig(
        base_path=str(Path(tmpdir) / "memory"),
        content_path=str(Path(tmpdir) / "memory" / "content"),
        enable_vector=False,
        default_agent_id="test-agent",
        default_agent_name="TestBot",
    )
    manager = MemoryManager(config=config)

    # Add and simulate high access
    shards = manager.promote_to_long_term("Important Python knowledge")
    shard_id = shards[0].id

    # Simulate multiple accesses
    for _ in range(15):
        manager.search("Python")

    stats = manager.get_stats()
    print(f"  ✓ After 15 accesses: {stats['shards']} shards")

    promotion_report = manager.run_promotion_cycle()
    print(f"  ✓ Promotion report: promoted={len(promotion_report.get('promoted', []))}")

# Test 6: Full maintenance cycle
print("\n--- Test 6: Full Maintenance Cycle ---")
with tempfile.TemporaryDirectory() as tmpdir:
    config = MemoryManagerConfig(
        base_path=str(Path(tmpdir) / "memory"),
        content_path=str(Path(tmpdir) / "memory" / "content"),
        enable_vector=False,
        default_agent_id="test-agent",
        default_agent_name="TestBot",
    )
    manager = MemoryManager(config=config)

    manager.promote_to_long_term("Fact 1")
    manager.promote_to_long_term("Fact 2")
    manager.append_to_short_term("Dialogue")

    report = manager.run_maintenance()
    print(f"  ✓ Maintenance report: promoted={len(report['promoted'])}, deleted={len(report['deleted'])}, archived={len(report['archived'])}")

print("\n" + "=" * 60)
print("✅ All Phase 4 integration tests passed!")
print("=" * 60)