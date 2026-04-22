"""Memory system enumeration types."""

from __future__ import annotations

from enum import Enum


class ShardType(str, Enum):
    """Memory shard content type."""

    FACT = "fact"              # 确定性事实
    PREFERENCE = "preference"  # 用户偏好
    EVENT = "event"            # 事件记录
    DIALOGUE = "dialogue"      # 对话片段
    SKILL = "skill"            # 技能/能力


class ShardSource(str, Enum):
    """Memory shard origin source."""

    USER_TOLD = "user_told"    # 用户直接告知
    SYSTEM_INFER = "system_infer"  # 系统推断
    EXTRACT = "extract"        # 从对话提取
    IMPORTED = "imported"      # 从迁移包导入


class ChunkType(str, Enum):
    """Memory chunk aggregation type."""

    PREFERENCE = "preference"  # 偏好聚合块
    SKILL = "skill"            # 技能聚合块
    KNOWLEDGE = "knowledge"    # 知识聚合块
    HISTORY = "history"        # 历史聚合块


class ClusterType(str, Enum):
    """Memory cluster functional domain."""

    IDENTITY = "identity"      # 身份核心（必须迁移）
    CAPABILITY = "capability"  # 能力技能（必须迁移）
    RELATIONSHIP = "relationship"  # 人际关系（可选迁移）
    KNOWLEDGE = "knowledge"    # 知识储备（可选迁移）
    EXPERIENCE = "experience"  # 经验教训（可选迁移）


class MemoryTier(str, Enum):
    """Memory lifecycle tier."""

    WORKING = "working"        # 工作记忆（当前对话）
    SHORT_TERM = "short_term"  # 短期记忆（7-30天）
    LONG_TERM = "long_term"    # 长期记忆（持久）