"""Tests for MemoryManager."""

import sys
sys.path.insert(0, "src")

import tempfile
from pathlib import Path

import pytest

# Import directly from memory subpackage (bypass mindbot.__init__)
from mindbot.memory import (
    ClusterType,
    ForgetReport,
    MemoryManager,
    MemoryManagerConfig,
    ShardType,
)


class TestMemoryManager:
    """Test MemoryManager."""

    @pytest.fixture()
    def temp_manager(self) -> MemoryManager:
        """Create a temporary memory manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = MemoryManagerConfig(
                base_path=str(Path(tmpdir) / "memory"),
                content_path=str(Path(tmpdir) / "memory" / "content"),
                default_agent_id="test-agent",
                default_agent_name="TestBot",
            )
            yield MemoryManager(config=config)

    def test_initialization(self, temp_manager: MemoryManager) -> None:
        """Test manager initialization."""
        profile = temp_manager.get_profile()
        assert profile.agent_id == "test-agent"
        assert profile.agent_name == "TestBot"

        stats = temp_manager.get_stats()
        assert stats["clusters"] == 5  # Default cluster types

    def test_append_to_short_term(self, temp_manager: MemoryManager) -> None:
        """Test appending short-term memory."""
        shards = temp_manager.append_to_short_term("User asked about weather")
        assert len(shards) == 1
        assert shards[0].text == "User asked about weather"
        assert shards[0].shard_type == ShardType.DIALOGUE

    def test_promote_to_long_term(self, temp_manager: MemoryManager) -> None:
        """Test promoting to long-term memory."""
        shards = temp_manager.promote_to_long_term("User prefers Python over JavaScript")
        assert len(shards) == 1
        assert shards[0].shard_type == ShardType.FACT

    def test_set_permanent_updates_stored_shard(self, temp_manager: MemoryManager) -> None:
        shards = temp_manager.promote_to_long_term("Permanent SDK fact")

        assert temp_manager.set_permanent(shards[0].id) is True

        loaded = temp_manager.get_shard(shards[0].id)
        assert loaded is not None
        assert loaded.is_permanent is True

    def test_append_preference(self, temp_manager: MemoryManager) -> None:
        """Test appending preference."""
        shard = temp_manager.append_preference("User likes dark mode")
        assert shard.text == "User likes dark mode"
        assert shard.shard_type == ShardType.PREFERENCE

    async def test_recall_returns_results(self, temp_manager: MemoryManager) -> None:
        """recall() returns matching :class:`MemoryHit` objects."""
        temp_manager.append_to_short_term("User mentioned Python programming")
        temp_manager.promote_to_long_term("Python is useful for data science")

        hits = await temp_manager.recall("Python")
        assert len(hits) > 0

        for hit in hits:
            assert hit.shard.text != ""
            assert "Python" in hit.shard.text
            assert hit.score > 0

    async def test_recall_updates_access_count(self, temp_manager: MemoryManager) -> None:
        """Recalling the same shard twice increases its access count."""
        temp_manager.promote_to_long_term("Test knowledge about Python")

        hits = await temp_manager.recall("Python")
        assert len(hits) > 0
        shard_id = hits[0].shard.id
        initial_count = hits[0].shard.access_count

        hits2 = await temp_manager.recall("Python")
        matching = [h for h in hits2 if h.shard.id == shard_id]
        if matching:
            assert matching[0].shard.access_count > initial_count

    def test_get_shard(self, temp_manager: MemoryManager) -> None:
        """Test getting specific shard."""
        shards = temp_manager.promote_to_long_term("Important fact")
        shard_id = shards[0].id

        loaded = temp_manager.get_shard(shard_id)
        assert loaded is not None
        assert loaded.text == "Important fact"

    def test_get_cluster_by_type(self, temp_manager: MemoryManager) -> None:
        """Test getting cluster by type."""
        cluster = temp_manager.get_cluster(ClusterType.IDENTITY)
        assert cluster is not None
        assert cluster.cluster_type == ClusterType.IDENTITY

    def test_forget_cycle(self, temp_manager: MemoryManager) -> None:
        """Test forget cycle execution."""
        # Add some memories
        temp_manager.append_to_short_term("Memory 1")
        temp_manager.append_to_short_term("Memory 2")

        # Run forget cycle (nothing should be deleted with default policy)
        report = temp_manager.run_forget_cycle()
        assert isinstance(report, ForgetReport)
        assert len(report.kept) >= 2  # New memories should be kept

    def test_compact_returns_count(self, temp_manager: MemoryManager) -> None:
        """Test compact method returns deleted count."""
        temp_manager.append_to_short_term("Test memory")

        deleted_count = temp_manager.compact()
        assert isinstance(deleted_count, int)
        assert deleted_count >= 0

    def test_get_stats(self, temp_manager: MemoryManager) -> None:
        """Test statistics retrieval."""
        temp_manager.append_to_short_term("Test")
        temp_manager.promote_to_long_term("Fact")

        stats = temp_manager.get_stats()
        assert "shards" in stats
        assert stats["shards"] >= 2

    def test_close(self, temp_manager: MemoryManager) -> None:
        """Test close method."""
        temp_manager.close()
        # Should not raise

    def test_export_profile(self, temp_manager: MemoryManager) -> None:
        """Test profile export."""
        temp_manager.append_preference("Prefers Python")

        package = temp_manager.export_profile()
        assert package.format == "mindbot-memory-v1.0"
        assert package.profile.agent_id == "test-agent"
        assert len(package.clusters) > 0
        assert len(package.shards) > 0


class TestMemoryManagerCompatibility:
    """Test API compatibility with old implementation."""

    @pytest.fixture()
    def temp_manager(self) -> MemoryManager:
        """Create a temporary memory manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = MemoryManagerConfig(
                base_path=str(Path(tmpdir) / "memory"),
                content_path=str(Path(tmpdir) / "memory" / "content"),
            )
            yield MemoryManager(config=config)

    async def test_recall_signature(self, temp_manager: MemoryManager) -> None:
        """recall() takes (query, top_k, cluster_type) and returns a list."""
        results = await temp_manager.recall("test query", top_k=3)
        assert isinstance(results, list)

        results2 = await temp_manager.recall("test", top_k=5, cluster_type=None)
        assert isinstance(results2, list)

    def test_append_to_short_term_returns_list(self, temp_manager: MemoryManager) -> None:
        """Test append_to_short_term returns list."""
        result = temp_manager.append_to_short_term("content")
        assert isinstance(result, list)

    def test_promote_to_long_term_returns_list(self, temp_manager: MemoryManager) -> None:
        """Test promote_to_long_term returns list."""
        result = temp_manager.promote_to_long_term("content")
        assert isinstance(result, list)

    def test_compact_returns_int(self, temp_manager: MemoryManager) -> None:
        """Test compact returns integer."""
        result = temp_manager.compact()
        assert isinstance(result, int)

    def test_close_exists(self, temp_manager: MemoryManager) -> None:
        """Test close method exists."""
        temp_manager.close()


class TestForgetPolicy:
    """Test forget policy integration."""

    def test_new_memory_protected(self) -> None:
        """Test new memories are protected from forget."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = MemoryManagerConfig(
                base_path=str(Path(tmpdir) / "memory"),
                content_path=str(Path(tmpdir) / "memory" / "content"),
            )
            manager = MemoryManager(config=config)

            # Add memory
            manager.append_to_short_term("New memory")

            # Run forget - should be kept due to recent protection
            report = manager.run_forget_cycle()
            assert len(report.deleted) == 0

    def test_permanent_memory_not_deleted(self) -> None:
        """Test permanent memories are never deleted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = MemoryManagerConfig(
                base_path=str(Path(tmpdir) / "memory"),
                content_path=str(Path(tmpdir) / "memory" / "content"),
            )
            manager = MemoryManager(config=config)

            # Add and mark permanent
            shards = manager.promote_to_long_term("Important permanent fact")
            shard = manager.get_shard(shards[0].id)
            if shard:
                # Simulate permanent marking
                index = manager._index_store.get_shard_index(shard.id)
                if index:
                    index.is_permanent = True
                    manager._index_store.update_shard_index(shard.id, index)

            report = manager.run_forget_cycle()
            # Permanent should not be deleted
            for deleted_id in report.deleted:
                assert deleted_id != shards[0].id
