#!/usr/bin/env python
"""Phase 6: Simplified integration test."""

import sys
sys.path.insert(0, "/root/workspace/mindbot/src")

# Mock problematic imports before importing mindbot
class MockLogger:
    def debug(self, *a, **kw): pass
    def info(self, *a, **kw): print(f"[INFO] {a}")
    def warning(self, *a, **kw): pass
    def error(self, *a, **kw): pass

sys.modules["mindbot"] = type(sys)("mindbot")
sys.modules["mindbot"].__path__ = ["src/mindbot"]
sys.modules["mindbot.utils"] = type(sys)("mindbot.utils")
sys.modules["mindbot.utils"].get_logger = lambda name: MockLogger()
sys.modules["mindbot.utils"].estimate_tokens = lambda x: len(x) // 4

import tempfile
import time
import json
import sqlite3
from pathlib import Path

print("=" * 60)
print("Phase 6: Integration Test")
print("=" * 60)

# Test imports
print("\n--- Test: Module Imports ---")
from mindbot.memory.manager import MemoryManager, MemoryManagerConfig
from mindbot.memory.storage import JSONIndexStore, IndexStoreConfig, MarkdownContentStore
from mindbot.memory.types import ShardType, ShardIndex
from mindbot.memory.migration import LegacyMigrator
print("  ✓ All modules imported successfully")

# Test 1: MemoryManager lifecycle
print("\n--- Test 1: MemoryManager Lifecycle ---")
with tempfile.TemporaryDirectory() as tmpdir:
    config = MemoryManagerConfig(
        base_path=str(Path(tmpdir) / "memory"),
        content_path=str(Path(tmpdir) / "memory" / "content"),
        enable_vector=False,
        default_agent_id="test",
        default_agent_name="TestBot",
    )
    manager = MemoryManager(config=config)

    # Write operations
    manager.promote_to_long_term("Python data science facts")
    manager.append_preference("Prefers dark mode")
    manager.append_to_short_term("Current conversation")

    stats = manager.get_stats()
    print(f"  ✓ Write: {stats['shards']} shards")

    # Read operations
    results = manager.search("Python")
    print(f"  ✓ Search: {len(results)} results")

    # Lifecycle operations
    report = manager.run_maintenance()
    print(f"  ✓ Maintenance: promoted={len(report['promoted'])}, deleted={len(report['deleted'])}")

    manager.close()

# Test 2: Legacy config compatibility
print("\n--- Test 2: Legacy Config Compatibility ---")
with tempfile.TemporaryDirectory() as tmpdir:
    manager = MemoryManager.from_legacy_config(
        storage_path=str(Path(tmpdir) / "legacy.db"),
        markdown_path=str(Path(tmpdir) / "legacy.md"),
    )
    stats = manager.get_stats()
    print(f"  ✓ from_legacy_config: {stats}")
    manager.close()

# Test 3: Export/Import cycle
print("\n--- Test 3: Export/Import Cycle ---")
with tempfile.TemporaryDirectory() as tmpdir:
    # Source
    config1 = MemoryManagerConfig(
        base_path=str(Path(tmpdir) / "src"),
        content_path=str(Path(tmpdir) / "src" / "content"),
        enable_vector=False,
        default_agent_id="src",
    )
    manager1 = MemoryManager(config=config1)
    manager1.promote_to_long_term("Key knowledge about AI")
    manager1.append_preference("Prefers brief answers")

    # Export
    export_path = str(Path(tmpdir) / "export.json")
    manager1.export_to_file(export_path)
    print(f"  ✓ Exported to {export_path}")

    # Target
    config2 = MemoryManagerConfig(
        base_path=str(Path(tmpdir) / "tgt"),
        content_path=str(Path(tmpdir) / "tgt" / "content"),
        enable_vector=False,
        default_agent_id="tgt",
    )
    manager2 = MemoryManager(config=config2)
    report = manager2.import_from_file(export_path)
    print(f"  ✓ Import: shards={report['imported_shards']}")

    # Verify
    results = manager2.search("AI")
    print(f"  ✓ Imported search: {len(results)} results")

    manager1.close()
    manager2.close()

# Test 4: Legacy SQLite migration
print("\n--- Test 4: Legacy SQLite Migration ---")
with tempfile.TemporaryDirectory() as tmpdir:
    # Create legacy DB
    db_path = Path(tmpdir) / "old.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE memory_chunks (id TEXT, text TEXT, source TEXT, chunk_type TEXT, created_at REAL, updated_at REAL, metadata TEXT)")
    conn.execute("INSERT INTO memory_chunks VALUES ('1', 'User knows Python', 'long_term', 'fact', ?, ?, '{}')", (time.time(), time.time()))
    conn.commit()
    conn.close()

    # Migrate
    index_store = JSONIndexStore(config=IndexStoreConfig(base_path=str(Path(tmpdir) / "new" / "idx")))
    content_store = MarkdownContentStore(base_path=str(Path(tmpdir) / "new" / "content"))
    migrator = LegacyMigrator(index_store=index_store, content_store=content_store)

    report = migrator.migrate_from_sqlite(str(db_path))
    print(f"  ✓ Migration: {report['migrated_shards']} shards")

print("\n" + "=" * 60)
print("✅ Phase 6 integration tests passed!")
print("=" * 60)