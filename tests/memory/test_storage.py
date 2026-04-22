"""Tests for memory storage layer."""

import tempfile
from pathlib import Path

import pytest

from mindbot.memory.storage import (
    IndexStoreConfig,
    JSONIndexStore,
    MarkdownContentStore,
)
from mindbot.memory.types import (
    ClusterType,
    MemoryChunk,
    MemoryCluster,
    MemoryProfile,
    ShardIndex,
    ShardSource,
    ShardType,
)


class TestMarkdownContentStore:
    """Test MarkdownContentStore."""

    @pytest.fixture()
    def temp_store(self) -> MarkdownContentStore:
        """Create a temporary content store."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield MarkdownContentStore(base_path=tmpdir)

    def test_write_and_read_shard(self, temp_store: MarkdownContentStore) -> None:
        """Test writing and reading a shard."""
        shard_id = "test-shard-001"
        content = "This is the test content for the shard."
        metadata = {"shard_type": "fact", "source": "user_told"}

        temp_store.write_shard(shard_id, content, metadata)

        # Read back
        read_content = temp_store.read_shard(shard_id)
        assert read_content == content

    def test_update_shard(self, temp_store: MarkdownContentStore) -> None:
        """Test updating shard content."""
        shard_id = "test-shard"
        temp_store.write_shard(shard_id, "original content")

        temp_store.update_shard(shard_id, "updated content")

        read = temp_store.read_shard(shard_id)
        assert read == "updated content"

    def test_delete_shard(self, temp_store: MarkdownContentStore) -> None:
        """Test deleting a shard."""
        shard_id = "to-delete"
        temp_store.write_shard(shard_id, "content")
        assert temp_store.shard_exists(shard_id)

        temp_store.delete_shard(shard_id)
        assert not temp_store.shard_exists(shard_id)

    def test_archive_and_unarchive(self, temp_store: MarkdownContentStore) -> None:
        """Test archiving and unarchiving a shard."""
        shard_id = "to-archive"
        temp_store.write_shard(shard_id, "content")

        # Archive
        archive_path = temp_store.archive_shard(shard_id)
        assert not temp_store.shard_exists(shard_id)
        assert archive_path.exists()

        # Unarchive
        restore_path = temp_store.unarchive_shard(shard_id)
        assert temp_store.shard_exists(shard_id)

    def test_search_by_keyword(self, temp_store: MarkdownContentStore) -> None:
        """Test keyword search."""
        temp_store.write_shard("shard-1", "Python is great for data science")
        temp_store.write_shard("shard-2", "JavaScript for web development")
        temp_store.write_shard("shard-3", "Python machine learning")

        matches = temp_store.search_by_keyword("Python")
        assert len(matches) == 2
        assert "shard-1" in matches
        assert "shard-3" in matches

    def test_write_chunk_aggregate(self, temp_store: MarkdownContentStore) -> None:
        """Test writing chunk aggregate."""
        shards = [
            ("shard-1", "First shard content"),
            ("shard-2", "Second shard content"),
        ]
        path = temp_store.write_chunk_aggregate(
            chunk_id="chunk-001",
            chunk_name="TestChunk",
            shards=shards,
        )
        assert path.exists()

        content = temp_store.read_chunk_aggregate("chunk-001")
        assert "First shard content" in content
        assert "Second shard content" in content

    def test_get_stats(self, temp_store: MarkdownContentStore) -> None:
        """Test statistics."""
        temp_store.write_shard("s1", "content 1")
        temp_store.write_shard("s2", "content 2")
        temp_store.write_chunk_aggregate("c1", "Chunk", [("s1", "content")])

        stats = temp_store.get_stats()
        assert stats["shards"] == 2
        assert stats["chunks"] == 1


class TestJSONIndexStore:
    """Test JSONIndexStore."""

    @pytest.fixture()
    def temp_store(self) -> JSONIndexStore:
        """Create a temporary index store."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = IndexStoreConfig(base_path=tmpdir)
            yield JSONIndexStore(config=config)

    def test_ensure_default_structure(self, temp_store: JSONIndexStore) -> None:
        """Test default structure creation."""
        profile = temp_store.ensure_default_structure("test-agent", "TestBot")

        assert profile.agent_id == "test-agent"
        assert profile.agent_name == "TestBot"
        assert len(profile.cluster_ids) == 5  # All cluster types

    def test_profile_operations(self, temp_store: JSONIndexStore) -> None:
        """Test profile CRUD."""
        profile = MemoryProfile.create(
            agent_id="custom-agent",
            agent_name="CustomBot",
            identity_definition="A custom agent",
        )
        temp_store.save_profile(profile)

        loaded = temp_store.load_profile("custom-agent")
        assert loaded is not None
        assert loaded.agent_name == "CustomBot"

        ids = temp_store.list_profiles()
        assert "custom-agent" in ids

    def test_cluster_operations(self, temp_store: JSONIndexStore) -> None:
        """Test cluster CRUD."""
        temp_store.ensure_default_structure("test-agent")

        cluster = MemoryCluster.create(
            name="CustomCluster",
            cluster_type=ClusterType.KNOWLEDGE,
            profile_id="test-agent",
        )
        temp_store.save_cluster(cluster)

        loaded = temp_store.load_cluster(cluster.id)
        assert loaded is not None
        assert loaded.name == "CustomCluster"

        # Get by type
        found = temp_store.get_cluster_by_type(ClusterType.KNOWLEDGE)
        assert found is not None

    def test_chunk_operations(self, temp_store: JSONIndexStore) -> None:
        """Test chunk CRUD."""
        temp_store.ensure_default_structure("test-agent")
        cluster = temp_store.get_cluster_by_type(ClusterType.KNOWLEDGE)

        chunk = MemoryChunk.create(
            name="TestChunk",
            cluster_id=cluster.id if cluster else "",
        )
        temp_store.save_chunk(chunk)

        loaded = temp_store.load_chunk(chunk.id)
        assert loaded is not None

        by_name = temp_store.get_chunk_by_name("TestChunk")
        assert by_name is not None

    def test_shard_index_operations(self, temp_store: JSONIndexStore) -> None:
        """Test shard index CRUD."""
        index = ShardIndex.create(
            shard_id="test-shard",
            markdown_path="shards/test-shard.md",
            summary="Test summary",
            shard_type=ShardType.FACT,
        )
        temp_store.update_shard_index("test-shard", index)

        loaded = temp_store.get_shard_index("test-shard")
        assert loaded is not None
        assert loaded.summary == "Test summary"

        # Update
        loaded.touch()
        temp_store.update_shard_index("test-shard", loaded)
        assert loaded.access_count == 1

        # Delete
        temp_store.delete_shard_index("test-shard")
        assert temp_store.get_shard_index("test-shard") is None

    def test_search_by_keywords(self, temp_store: JSONIndexStore) -> None:
        """Test keyword search in indices."""
        index1 = ShardIndex.create(
            shard_id="s1",
            markdown_path="s1.md",
            summary="Python programming",
            keywords=["python", "coding"],
        )
        index2 = ShardIndex.create(
            shard_id="s2",
            markdown_path="s2.md",
            summary="JavaScript web development",
            keywords=["javascript", "web"],
        )
        temp_store.update_shard_index("s1", index1)
        temp_store.update_shard_index("s2", index2)

        matches = temp_store.search_indices_by_keywords(["python"])
        assert len(matches) == 1
        assert matches[0].shard_id == "s1"

    def test_rebuild_stats(self, temp_store: JSONIndexStore) -> None:
        """Test hierarchy stats rebuild."""
        profile = temp_store.ensure_default_structure("test-agent")

        cluster = temp_store.get_cluster_by_type(ClusterType.KNOWLEDGE)
        if cluster:
            chunk = MemoryChunk.create(name="TestChunk", cluster_id=cluster.id)
            chunk.add_shard("shard-1")
            temp_store.save_chunk(chunk)
            cluster.add_chunk(chunk.id)
            temp_store.save_cluster(cluster)

            index = ShardIndex.create(
                shard_id="shard-1",
                markdown_path="shard-1.md",
                summary="test",
                chunk_id=chunk.id,
                cluster_id=cluster.id,
            )
            index.access_count = 5
            temp_store.update_shard_index("shard-1", index)

            temp_store.rebuild_hierarchy_stats()

            updated_chunk = temp_store.load_chunk(chunk.id)
            assert updated_chunk is not None
            assert updated_chunk.total_access == 5

    def test_get_stats(self, temp_store: JSONIndexStore) -> None:
        """Test store statistics."""
        temp_store.ensure_default_structure("test-agent")

        stats = temp_store.get_stats()
        assert stats["profiles"] == 1
        assert stats["clusters"] == 5  # Default 5 cluster types


class TestIntegration:
    """Integration tests for storage layer."""

    def test_full_write_read_flow(self) -> None:
        """Test full flow from content store to index store."""
        with tempfile.TemporaryDirectory() as tmpdir:
            content_path = Path(tmpdir) / "content"
            index_path = Path(tmpdir) / "index"

            content_store = MarkdownContentStore(base_path=str(content_path))
            index_store = JSONIndexStore(
                config=IndexStoreConfig(base_path=str(index_path))
            )

            # Setup structure
            profile = index_store.ensure_default_structure("test-agent")

            # Write content
            shard_id = "shard-001"
            content = "This is important knowledge about Python."
            content_store.write_shard(shard_id, content)

            # Write index
            index = ShardIndex.create(
                shard_id=shard_id,
                markdown_path=f"shards/{shard_id}.md",
                summary="Python knowledge",
                shard_type=ShardType.FACT,
            )
            index_store.update_shard_index(shard_id, index)

            # Verify
            read_content = content_store.read_shard(shard_id)
            assert read_content == content

            read_index = index_store.get_shard_index(shard_id)
            assert read_index is not None
            assert read_index.summary == "Python knowledge"