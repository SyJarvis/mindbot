#!/usr/bin/env python3
"""Example 13: 四级向量记忆系统演示。

演示 MindBot Memory System 的核心功能：
- 四级结构：Profile → Cluster → Chunk → Shard
- 三层存储：JSON索引 + Markdown内容 + LanceDB向量
- 语义检索：向量 + 关键词混合搜索
- 智能更新：去重、合并、修正
- 遗忘机制：多维度评分与清理
- 迁移协议：Agent身份导出导入

Run::

    python -m examples.13_memory_system
    python -m examples.13_memory_system --demo search
    python -m examples.13_memory_system --demo forget
    python -m examples.13_memory_system --demo export
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path

# 直接设置路径，绕过完整包导入（Python 3.9 兼容）
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Mock mindbot.utils 避免深层导入问题
class MockLogger:
    def debug(self, *a, **kw): pass
    def info(self, *a, **kw): pass
    def warning(self, *a, **kw): pass
    def error(self, *a, **kw): pass

class MockUtils:
    @staticmethod
    def get_logger(name):
        return MockLogger()
    @staticmethod
    def estimate_tokens(text):
        return len(text) // 4

sys.modules["mindbot.utils"] = MockUtils()

# 现在可以安全导入 memory 模块
from mindbot.memory import (
    ChunkType,
    ClusterType,
    ForgetPolicy,
    ForgetReport,
    MemoryManager,
    MemoryManagerConfig,
    MemoryShard,
    ShardSource,
    ShardType,
)


def create_temp_manager() -> MemoryManager:
    """创建临时目录的 MemoryManager 用于演示。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir) / "memory"
        config = MemoryManagerConfig(
            base_path=str(base),
            content_path=str(base / "content"),
            default_agent_id="demo-agent",
            default_agent_name="DemoBot",
        )
        return MemoryManager(config=config)


async def demo_basic_operations() -> None:
    """演示基础操作：四级结构和读写。"""
    print("=" * 60)
    print("Demo 1: 四级结构与基础操作")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir) / "memory"
        config = MemoryManagerConfig(
            base_path=str(base),
            content_path=str(base / "content"),
            default_agent_id="demo-agent",
            default_agent_name="DemoBot",
        )
        manager = MemoryManager(config=config)

        # 1. Profile - Agent 身份档案
        print("\n[1] Profile 层级 - Agent 身份")
        profile = manager.get_profile()
        print(f"  agent_id: {profile.agent_id}")
        print(f"  agent_name: {profile.agent_name}")
        print(f"  clusters: {len(profile.cluster_ids)}")

        # 2. Cluster - 功能域
        print("\n[2] Cluster 层级 - 功能域")
        for cluster_type in [ClusterType.IDENTITY, ClusterType.CAPABILITY, ClusterType.KNOWLEDGE]:
            cluster = manager.get_cluster(cluster_type)
            if cluster:
                print(f"  {cluster_type.value}: {cluster.id} ({len(cluster.chunk_ids)} chunks)")

        # 3. 写入 Shard - 原子记忆
        print("\n[3] 写入 Shard - 原子记忆")
        shards = manager.promote_to_long_term("用户喜欢使用 Python 进行数据分析")
        print(f"  写入 1 条 FACT: {shards[0].id[:8]}...")

        shard = manager.append_preference("用户偏好深色主题界面")
        print(f"  写入 1 条 PREFERENCE: {shard.id[:8]}...")

        dialogue = manager.append_to_short_term("用户问：如何学习机器学习？")
        print(f"  写入 1 条 DIALOGUE: {dialogue[0].id[:8]}...")

        # 4. 统计
        print("\n[4] 记忆统计")
        stats = manager.get_stats()
        print(f"  总 shards: {stats['shards']}")
        print(f"  总 clusters: {stats['clusters']}")
        print(f"  总 chunks: {stats['chunks']}")

        manager.close()

    print("\n✓ 基础操作演示完成")


async def demo_search() -> None:
    """演示检索功能：混合检索。"""
    print("=" * 60)
    print("Demo 2: 混合检索")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir) / "memory"
        config = MemoryManagerConfig(
            base_path=str(base),
            content_path=str(base / "content"),
        )
        manager = MemoryManager(config=config)

        # 写入多条记忆
        print("\n[1] 写入测试记忆")
        memories = [
            "Python 是一种流行的编程语言，适合数据科学",
            "用户偏好使用 VS Code 作为开发工具",
            "机器学习需要数学基础：线性代数和概率论",
            "深度学习框架包括 TensorFlow 和 PyTorch",
            "用户喜欢猫，养了一只叫小花的猫",
        ]

        for mem in memories:
            manager.promote_to_long_term(mem)
        print(f"  写入 {len(memories)} 条记忆")

        # 关键词检索
        print("\n[2] 关键词检索: 'Python'")
        results = manager.search("Python", top_k=3)
        for i, shard in enumerate(results):
            print(f"  [{i+1}] {shard.text[:50]}... (access_count={shard.access_count})")

        # 语义检索
        print("\n[3] 语义检索: '编程语言推荐'")
        results = manager.search("编程语言推荐", top_k=3)
        for i, shard in enumerate(results):
            print(f"  [{i+1}] {shard.text[:50]}...")

        # 检索特定类型
        print("\n[4] 检索偏好类型")
        results = manager.search("偏好", top_k=2)
        for shard in results:
            print(f"  PREFERENCE: {shard.text[:50]}...")

        manager.close()

    print("\n✓ 检索演示完成")


async def demo_forget() -> None:
    """演示遗忘机制：多维度评分与清理。"""
    print("=" * 60)
    print("Demo 3: 遗忘机制")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir) / "memory"
        config = MemoryManagerConfig(
            base_path=str(base),
            content_path=str(base / "content"),
            forget_policy=ForgetPolicy(
                forget_threshold=0.70,
                delete_threshold=0.85,
                archive_threshold=0.75,
            ),
        )
        manager = MemoryManager(config=config)

        print("\n[1] 写入记忆")
        for i in range(5):
            manager.append_to_short_term(f"测试记忆 #{i+1}")
        print(f"  写入 5 条短期记忆")

        print("\n[2] 遗忘评分因素")
        print("  - 访问频率 (25%): 低访问 → 高遗忘倾向")
        print("  - 时效性 (20%): 越久 → 高遗忘倾向")
        print("  - 冗余度 (25%): 高相似 → 高遗忘倾向")
        print("  - 信息密度 (15%): 内容短 → 高遗忘倾向")
        print("  - 来源类型 (15%): EXTRACT 来源 → 较高遗忘倾向")

        print("\n[3] 执行遗忘周期")
        report: ForgetReport = manager.run_forget_cycle()
        print(f"  deleted: {len(report.deleted)}")
        print(f"  archived: {len(report.archived)}")
        print(f"  kept: {len(report.kept)}")

        print("\n[4] 新记忆保护")
        print("  创建 3 天内的记忆不会被删除")

        print("\n[5] 永久保护标记")
        shards = manager.promote_to_long_term("重要永久记忆：用户姓名是张三")
        if shards:
            index = manager._index_store.get_shard_index(shards[0].id)
            if index:
                index.is_permanent = True
                manager._index_store.update_shard_index(shards[0].id, index)
                print(f"  已标记为永久: {shards[0].id[:8]}...")

        manager.close()

    print("\n✓ 遗忘机制演示完成")


async def demo_export_import() -> None:
    """演示迁移协议：Agent身份导出导入。"""
    print("=" * 60)
    print("Demo 4: 迁移协议")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir) / "memory"
        export_file = Path(tmpdir) / "export.json"

        # 源 Manager
        config = MemoryManagerConfig(
            base_path=str(base),
            content_path=str(base / "content"),
            default_agent_id="source-agent",
            default_agent_name="SourceBot",
        )
        source_manager = MemoryManager(config=config)

        print("\n[1] 源 Agent 写入记忆")
        source_manager.promote_to_long_term("源 Agent 记忆 1：用户喜欢 Python")
        source_manager.append_preference("源 Agent 记忆 2：偏好简洁回答")
        source_stats = source_manager.get_stats()
        print(f"  shards: {source_stats['shards']}")

        print("\n[2] 导出 Agent 身份")
        package = source_manager.export_profile()
        export_data = package.to_dict()
        print(f"  format: {export_data['format']}")
        print(f"  profile: {export_data['profile']['agent_id']}")
        print(f"  shards: {len(export_data['shards'])}")

        # 写入导出文件
        import json
        with open(export_file, "w") as f:
            json.dump(export_data, f, indent=2)
        print(f"  已保存到: {export_file}")

        source_manager.close()

        # 目标 Manager - 使用 import_from_file
        print("\n[3] 导入到新 Agent")
        target_base = Path(tmpdir) / "target_memory"
        target_config = MemoryManagerConfig(
            base_path=str(target_base),
            content_path=str(target_base / "content"),
            default_agent_id="target-agent",
            default_agent_name="TargetBot",
        )
        target_manager = MemoryManager(config=target_config)

        # 导入
        target_manager.import_from_file(str(export_file))

        target_stats = target_manager.get_stats()
        print(f"  导入后 shards: {target_stats['shards']}")

        print("\n[4] 验证导入结果")
        results = target_manager.search("Python")
        if results:
            print(f"  检索到导入记忆: {results[0].text[:40]}...")

        target_manager.close()

    print("\n✓ 迁移协议演示完成")


async def demo_legacy_migration() -> None:
    """演示从旧版 SQLite 迁移。"""
    print("=" * 60)
    print("Demo 5: Legacy SQLite 迁移")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建模拟的旧版数据
        import sqlite3

        legacy_db = Path(tmpdir) / "legacy_memory.db"
        conn = sqlite3.connect(str(legacy_db))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_chunks (
                id TEXT PRIMARY KEY,
                content TEXT,
                role TEXT,
                created_at REAL,
                metadata TEXT
            )
        """)
        conn.execute("""
            INSERT INTO memory_chunks VALUES
            ('old-1', '旧版记忆：用户喜欢 Python 编程', 'user', 1700000000, '{}'),
            ('old-2', '旧版记忆：用户偏好详细解释', 'assistant', 1700000100, '{}')
        """)
        conn.commit()
        conn.close()
        print(f"\n[1] 创建旧版数据库: {legacy_db}")

        # 迁移到新系统
        new_base = Path(tmpdir) / "new_memory"
        config = MemoryManagerConfig(
            base_path=str(new_base),
            content_path=str(new_base / "content"),
        )
        manager = MemoryManager(config=config)

        print("\n[2] 执行迁移")
        from mindbot.memory.migration import LegacyMigrator

        migrator = LegacyMigrator(
            index_store=manager._index_store,
            content_store=manager._content_store,
        )
        report = migrator.migrate_from_sqlite(str(legacy_db))
        print(f"  迁移 shards: {report.get('total_shards', 0)}")
        print(f"  成功: {report.get('success', 0)}")
        print(f"  失败: {report.get('failed', 0)}")

        print("\n[3] 验证迁移结果")
        results = manager.search("Python")
        if results:
            print(f"  检索到迁移记忆: {results[0].text[:40]}...")

        manager.close()

    print("\n✓ Legacy 迁移演示完成")


async def main() -> None:
    parser = argparse.ArgumentParser(description="MindBot 四级向量记忆系统演示")
    parser.add_argument(
        "--demo",
        choices=["basic", "search", "forget", "export", "legacy", "all"],
        default="all",
        help="选择演示模块",
    )
    args = parser.parse_args()

    demos = {
        "basic": demo_basic_operations,
        "search": demo_search,
        "forget": demo_forget,
        "export": demo_export_import,
        "legacy": demo_legacy_migration,
    }

    if args.demo == "all":
        for name, demo_func in demos.items():
            await demo_func()
    else:
        await demos[args.demo]()


if __name__ == "__main__":
    asyncio.run(main())