#!/usr/bin/env python
"""Integration test for Phase 5: Migration protocol."""

import sys, importlib.util, tempfile, time, json, sqlite3
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
sys.modules["mindbot.memory.storage"] = storage_init
sys.modules["mindbot.memory.storage.index_store"] = index_store_mod
sys.modules["mindbot.memory.storage.content_store"] = content_store_mod
sys.modules["mindbot.memory.storage.vector_store"] = vs_mod

# Migration
package_mod = load_module("mindbot.memory.migration.package", src_path / "mindbot" / "memory" / "migration" / "package.py")
exporter_mod = load_module("mindbot.memory.migration.exporter", src_path / "mindbot" / "memory" / "migration" / "exporter.py")
importer_mod = load_module("mindbot.memory.migration.importer", src_path / "mindbot" / "memory" / "migration" / "importer.py")
legacy_mod = load_module("mindbot.memory.migration.legacy_migrator", src_path / "mindbot" / "memory" / "migration" / "legacy_migrator.py")

migration_init = type(sys)("mindbot.memory.migration")
migration_init.MigrationPackage = package_mod.MigrationPackage
migration_init.ShardData = package_mod.ShardData
migration_init.MemoryExporter = exporter_mod.MemoryExporter
migration_init.ExportOptions = exporter_mod.ExportOptions
migration_init.MemoryImporter = importer_mod.MemoryImporter
migration_init.ImportOptions = importer_mod.ImportOptions
migration_init.LegacyMigrator = legacy_mod.LegacyMigrator
sys.modules["mindbot.memory.migration"] = migration_init
sys.modules["mindbot.memory.migration.package"] = package_mod
sys.modules["mindbot.memory.migration.exporter"] = exporter_mod
sys.modules["mindbot.memory.migration.importer"] = importer_mod
sys.modules["mindbot.memory.migration.legacy_migrator"] = legacy_mod

# Lifecycle stubs
summarizer_mod = load_module("mindbot.memory.lifecycle.summarizer", src_path / "mindbot" / "memory" / "lifecycle" / "summarizer.py")
updater_mod = load_module("mindbot.memory.lifecycle.updater", src_path / "mindbot" / "memory" / "lifecycle" / "updater.py")
forgetter_mod = load_module("mindbot.memory.lifecycle.forgetter", src_path / "mindbot" / "memory" / "lifecycle" / "forgetter.py")
promoter_mod = load_module("mindbot.memory.lifecycle.promoter", src_path / "mindbot" / "memory" / "lifecycle" / "promoter.py")

lifecycle_init = type(sys)("mindbot.memory.lifecycle")
lifecycle_init.SummaryGenerator = summarizer_mod.SummaryGenerator
lifecycle_init.MemoryUpdater = updater_mod.MemoryUpdater
lifecycle_init.UpdateResult = updater_mod.UpdateResult
lifecycle_init.MemoryForgetter = forgetter_mod.MemoryForgetter
lifecycle_init.MemoryPromoter = promoter_mod.MemoryPromoter
sys.modules["mindbot.memory.lifecycle"] = lifecycle_init

# Embedder stub
embedder_init = type(sys)("mindbot.memory.embedder")
sys.modules["mindbot.memory.embedder"] = embedder_init
sys.modules["mindbot.memory.retrieval"] = type(sys)("mindbot.memory.retrieval")

# Manager
manager_mod = load_module("mindbot.memory.manager", src_path / "mindbot" / "memory" / "manager.py")
MemoryManager = manager_mod.MemoryManager
MemoryManagerConfig = manager_mod.MemoryManagerConfig

from mindbot.memory.storage.index_store import JSONIndexStore, IndexStoreConfig
from mindbot.memory.storage.content_store import MarkdownContentStore
from mindbot.memory.migration import MemoryExporter, ExportOptions, MemoryImporter, ImportOptions, MigrationPackage, LegacyMigrator

print("=" * 60)
print("Phase 5 Integration Test: Migration Protocol")
print("=" * 60)

# Test 1: MigrationPackage structure
print("\n--- Test 1: MigrationPackage Structure ---")
pkg = MigrationPackage()
pkg.profile = package_mod.ProfileData(agent_id="test", agent_name="TestBot")
pkg.clusters.append(package_mod.ClusterData(cluster_id="c1", name="Knowledge", cluster_type="knowledge", profile_id="test"))
pkg.chunks.append(package_mod.ChunkData(chunk_id="ch1", name="facts", cluster_id="c1"))
pkg.shards.append(package_mod.ShardData(shard_id="s1", text="Important fact", shard_type="fact", source="user_told", cluster_id="c1", chunk_id="ch1", created_at=time.time(), updated_at=time.time()))

checksum = pkg.compute_checksum()
print(f"  ✓ Package checksum: {checksum}")

stats = pkg.get_stats()
print(f"  ✓ Stats: {stats}")

# Test 2: Package serialization
print("\n--- Test 2: Package Serialization ---")
with tempfile.TemporaryDirectory() as tmpdir:
    file_path = Path(tmpdir) / "export.json"
    pkg.save_to_file(file_path)
    print(f"  ✓ Saved to {file_path}")

    loaded = MigrationPackage.load_from_file(file_path)
    print(f"  ✓ Loaded: {loaded.get_stats()}")
    assert loaded.checksum == pkg.checksum

# Test 3: MemoryExporter
print("\n--- Test 3: MemoryExporter ---")
with tempfile.TemporaryDirectory() as tmpdir:
    index_store = JSONIndexStore(config=IndexStoreConfig(base_path=str(Path(tmpdir) / "idx")))
    content_store = MarkdownContentStore(base_path=str(Path(tmpdir) / "content"))
    index_store.ensure_default_structure("src-agent", "SourceBot")

    # Add some data
    idx = ShardIndex.create(shard_id="s1", markdown_path="s1.md", summary="Test fact")
    idx.cluster_id = "cluster-knowledge"
    index_store.update_shard_index("s1", idx)
    content_store.write_shard("s1", "Full text of important fact", {"type": "test"})

    exporter = MemoryExporter(index_store=index_store, content_store=content_store)
    package = exporter.export()
    print(f"  ✓ Exported: {package.get_stats()}")
    assert package.profile is not None
    assert package.profile.agent_id == "src-agent"

# Test 4: MemoryImporter
print("\n--- Test 4: MemoryImporter ---")
with tempfile.TemporaryDirectory() as tmpdir:
    target_index = JSONIndexStore(config=IndexStoreConfig(base_path=str(Path(tmpdir) / "target" / "idx")))
    target_content = MarkdownContentStore(base_path=str(Path(tmpdir) / "target" / "content"))

    importer = MemoryImporter(index_store=target_index, content_store=target_content)

    # Create package to import
    pkg = MigrationPackage()
    pkg.profile = package_mod.ProfileData(agent_id="clone", agent_name="CloneBot", identity_definition="I am a clone")
    pkg.clusters.append(package_mod.ClusterData(cluster_id="c1", name="Knowledge", cluster_type="knowledge", profile_id="clone"))
    pkg.chunks.append(package_mod.ChunkData(chunk_id="ch1", name="facts", cluster_id="c1"))
    pkg.shards.append(package_mod.ShardData(
        shard_id="s1", text="Important imported fact", shard_type="fact",
        source="imported", cluster_id="c1", chunk_id="ch1",
        created_at=time.time(), updated_at=time.time()
    ))

    report = importer.import_package(pkg, options=ImportOptions(new_agent_id="new-agent", new_agent_name="NewBot"))
    print(f"  ✓ Import report: {report}")

    # Verify imported data
    profile = target_index.load_profile("new-agent")
    assert profile is not None
    print(f"  ✓ Imported profile: {profile.agent_name}")

# Test 5: Full export/import cycle via MemoryManager
print("\n--- Test 5: MemoryManager Export/Import ---")
with tempfile.TemporaryDirectory() as tmpdir:
    config1 = MemoryManagerConfig(
        base_path=str(Path(tmpdir) / "source"),
        content_path=str(Path(tmpdir) / "source" / "content"),
        enable_vector=False,
        default_agent_id="original",
        default_agent_name="OriginalBot",
    )
    manager1 = MemoryManager(config=config1)

    # Add memories
    manager1.promote_to_long_term("Important knowledge about Python")
    manager1.append_preference("User prefers dark mode")
    manager1.append_skill("Can analyze data with pandas")

    stats1 = manager1.get_stats()
    print(f"  ✓ Source manager: {stats1['shards']} shards")

    # Export
    export_file = str(Path(tmpdir) / "export.json")
    manager1.export_to_file(export_file)
    print(f"  ✓ Exported to file")

    # Import to new manager
    config2 = MemoryManagerConfig(
        base_path=str(Path(tmpdir) / "target"),
        content_path=str(Path(tmpdir) / "target" / "content"),
        enable_vector=False,
        default_agent_id="clone",
        default_agent_name="CloneBot",
    )
    manager2 = MemoryManager(config=config2)
    report = manager2.import_from_file(export_file, new_agent_id="clone")
    print(f"  ✓ Import report: shards={report['imported_shards']}")

    # Verify clone has same data
    results = manager2.search("Python")
    print(f"  ✓ Clone search 'Python': {len(results)} results")
    assert len(results) > 0

# Test 6: Legacy SQLite migration
print("\n--- Test 6: Legacy SQLite Migration ---")
with tempfile.TemporaryDirectory() as tmpdir:
    # Create fake legacy SQLite
    db_path = Path(tmpdir) / "legacy.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE memory_chunks (
            id TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            source TEXT DEFAULT 'short_term',
            chunk_type TEXT DEFAULT 'conversation',
            created_at REAL,
            updated_at REAL,
            metadata TEXT DEFAULT '{}'
        );
        CREATE VIRTUAL TABLE memory_fts USING fts5(id, text, source);
    """)
    # Insert test data
    conn.execute("INSERT INTO memory_chunks VALUES ('1', 'Python is great', 'long_term', 'fact', ?, ?, '{}')", (time.time(), time.time()))
    conn.execute("INSERT INTO memory_chunks VALUES ('2', 'User said hello', 'short_term', 'conversation', ?, ?, '{}')", (time.time(), time.time()))
    conn.commit()
    conn.close()

    print(f"  ✓ Created legacy DB with 2 records")

    # Migrate
    target_index = JSONIndexStore(config=IndexStoreConfig(base_path=str(Path(tmpdir) / "new" / "idx")))
    target_content = MarkdownContentStore(base_path=str(Path(tmpdir) / "new" / "content"))
    migrator = LegacyMigrator(index_store=target_index, content_store=target_content)

    report = migrator.migrate_from_sqlite(str(db_path), target_agent_id="migrated", target_agent_name="MigratedBot")
    print(f"  ✓ Migration report: shards={report['migrated_shards']}, chunks={report['migrated_chunks']}")

    # Verify migrated data
    profile = target_index.load_profile("migrated")
    assert profile is not None
    print(f"  ✓ Migrated profile exists")

    indices = target_index.load_all_indices()
    print(f"  ✓ Migrated indices: {len(indices)} shards")

print("\n" + "=" * 60)
print("✅ All Phase 5 integration tests passed!")
print("=" * 60)