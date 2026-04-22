"""Tests for memory data types."""

import pytest

from mindbot.memory.types import (
    ChunkType,
    ClusterType,
    ForgetPolicy,
    ForgetReport,
    MemoryChunk,
    MemoryCluster,
    MemoryProfile,
    MemoryShard,
    ShardIndex,
    ShardSource,
    ShardType,
)


class TestEnums:
    """Test enumeration types."""

    def test_shard_type_values(self) -> None:
        """Test ShardType enum values."""
        assert ShardType.FACT.value == "fact"
        assert ShardType.PREFERENCE.value == "preference"
        assert ShardType.EVENT.value == "event"
        assert ShardType.DIALOGUE.value == "dialogue"
        assert ShardType.SKILL.value == "skill"

    def test_cluster_type_values(self) -> None:
        """Test ClusterType enum values."""
        assert ClusterType.IDENTITY.value == "identity"
        assert ClusterType.CAPABILITY.value == "capability"
        assert ClusterType.KNOWLEDGE.value == "knowledge"

    def test_shard_source_values(self) -> None:
        """Test ShardSource enum values."""
        assert ShardSource.USER_TOLD.value == "user_told"
        assert ShardSource.SYSTEM_INFER.value == "system_infer"
        assert ShardSource.EXTRACT.value == "extract"
        assert ShardSource.IMPORTED.value == "imported"


class TestMemoryShard:
    """Test MemoryShard data class."""

    def test_create_shard(self) -> None:
        """Test factory method."""
        shard = MemoryShard.create(
            text="用户喜欢Python",
            shard_type=ShardType.PREFERENCE,
            source=ShardSource.USER_TOLD,
        )
        assert shard.id != ""
        assert shard.text == "用户喜欢Python"
        assert shard.shard_type == ShardType.PREFERENCE
        assert shard.source == ShardSource.USER_TOLD
        assert shard.created_at > 0

    def test_touch_updates_stats(self) -> None:
        """Test touch method updates access stats."""
        shard = MemoryShard.create(text="test")
        initial_count = shard.access_count
        shard.touch()
        assert shard.access_count == initial_count + 1
        assert shard.last_accessed_at > 0

    def test_update_text(self) -> None:
        """Test update_text method."""
        shard = MemoryShard.create(text="original")
        shard.update_text("updated")
        assert shard.text == "updated"
        assert shard.updated_at >= shard.created_at


class TestMemoryChunk:
    """Test MemoryChunk data class."""

    def test_create_chunk(self) -> None:
        """Test factory method."""
        chunk = MemoryChunk.create(
            name="Python_Skills",
            cluster_id="cluster-123",
            chunk_type=ChunkType.SKILL,
        )
        assert chunk.id != ""
        assert chunk.name == "Python_Skills"
        assert chunk.cluster_id == "cluster-123"
        assert chunk.chunk_type == ChunkType.SKILL

    def test_add_remove_shard(self) -> None:
        """Test shard management."""
        chunk = MemoryChunk.create(name="test", cluster_id="c1")
        chunk.add_shard("shard-1")
        assert "shard-1" in chunk.shard_ids
        assert chunk.shard_count == 1

        chunk.add_shard("shard-2")
        assert chunk.shard_count == 2

        chunk.remove_shard("shard-1")
        assert "shard-1" not in chunk.shard_ids
        assert chunk.shard_count == 1

    def test_duplicate_shard_not_added(self) -> None:
        """Test duplicate shard IDs are not added."""
        chunk = MemoryChunk.create(name="test", cluster_id="c1")
        chunk.add_shard("shard-1")
        chunk.add_shard("shard-1")
        assert chunk.shard_count == 1


class TestMemoryCluster:
    """Test MemoryCluster data class."""

    def test_create_cluster(self) -> None:
        """Test factory method."""
        cluster = MemoryCluster.create(
            name="Identity",
            cluster_type=ClusterType.IDENTITY,
            profile_id="profile-1",
        )
        assert cluster.id != ""
        assert cluster.name == "Identity"
        assert cluster.cluster_type == ClusterType.IDENTITY
        assert cluster.migration_priority == 1  # IDENTITY is highest priority
        assert cluster.is_core is True

    def test_cluster_type_sets_priority(self) -> None:
        """Test cluster type determines migration priority."""
        identity = MemoryCluster.create(
            name="id", cluster_type=ClusterType.IDENTITY, profile_id="p1"
        )
        assert identity.migration_priority == 1
        assert identity.is_core is True

        knowledge = MemoryCluster.create(
            name="know", cluster_type=ClusterType.KNOWLEDGE, profile_id="p1"
        )
        assert knowledge.migration_priority == 4
        assert knowledge.is_core is False

    def test_add_remove_chunk(self) -> None:
        """Test chunk management."""
        cluster = MemoryCluster.create(
            name="test", cluster_type=ClusterType.KNOWLEDGE, profile_id="p1"
        )
        cluster.add_chunk("chunk-1")
        assert "chunk-1" in cluster.chunk_ids
        assert cluster.total_chunks == 1

        cluster.remove_chunk("chunk-1")
        assert cluster.total_chunks == 0


class TestMemoryProfile:
    """Test MemoryProfile data class."""

    def test_create_profile(self) -> None:
        """Test factory method."""
        profile = MemoryProfile.create(
            agent_id="agent-001",
            agent_name="TestAgent",
            identity_definition="A helpful assistant",
        )
        assert profile.agent_id == "agent-001"
        assert profile.agent_name == "TestAgent"
        assert profile.identity_definition == "A helpful assistant"
        assert profile.created_at > 0

    def test_add_remove_cluster(self) -> None:
        """Test cluster management."""
        profile = MemoryProfile.create(agent_id="test", agent_name="Test")
        profile.add_cluster("cluster-1")
        assert "cluster-1" in profile.cluster_ids
        assert profile.total_clusters == 1

        profile.remove_cluster("cluster-1")
        assert profile.total_clusters == 0

    def test_get_identity_summary(self) -> None:
        """Test identity summary generation."""
        profile = MemoryProfile.create(
            agent_id="test",
            agent_name="TestAgent",
            identity_definition="Helpful assistant",
        )
        profile.personality_traits = {"friendliness": 0.8}
        profile.core_values = ["accuracy", "helpfulness"]

        summary = profile.get_identity_summary()
        assert "Name: TestAgent" in summary
        assert "Definition: Helpful assistant" in summary
        assert "friendliness" in summary


class TestShardIndex:
    """Test ShardIndex data class."""

    def test_create_index(self) -> None:
        """Test factory method."""
        index = ShardIndex.create(
            shard_id="shard-001",
            markdown_path="content/shards/shard-001.md",
            summary="Test summary",
            shard_type=ShardType.FACT,
        )
        assert index.shard_id == "shard-001"
        assert index.markdown_path == "content/shards/shard-001.md"
        assert index.summary == "Test summary"

    def test_summary_truncated(self) -> None:
        """Test summary is truncated to 100 chars."""
        long_summary = "This is a very long summary that should be truncated to 100 characters maximum length"
        index = ShardIndex.create(
            shard_id="test",
            markdown_path="path",
            summary=long_summary,
        )
        assert len(index.summary) <= 100

    def test_to_dict_and_from_dict(self) -> None:
        """Test serialization."""
        index = ShardIndex.create(
            shard_id="test-id",
            markdown_path="test.md",
            summary="test",
            shard_type=ShardType.PREFERENCE,
            keywords=["python", "coding"],
        )

        data = index.to_dict()
        assert data["shard_id"] == "test-id"
        assert data["shard_type"] == "preference"
        assert data["keywords"] == ["python", "coding"]

        restored = ShardIndex.from_dict(data)
        assert restored.shard_id == index.shard_id
        assert restored.shard_type == index.shard_type
        assert restored.keywords == index.keywords


class TestForgetPolicy:
    """Test ForgetPolicy configuration."""

    def test_default_weights(self) -> None:
        """Test default weight values."""
        policy = ForgetPolicy()
        assert policy.access_weight == 0.25
        assert policy.age_weight == 0.20
        assert policy.redundancy_weight == 0.25

        # Weights should sum to ~1.0
        total = (
            policy.access_weight
            + policy.age_weight
            + policy.redundancy_weight
            + policy.density_weight
            + policy.source_weight
        )
        assert total == 1.0

    def test_threshold_ordering(self) -> None:
        """Test thresholds are ordered correctly."""
        policy = ForgetPolicy()
        assert policy.forget_threshold < policy.archive_threshold < policy.delete_threshold