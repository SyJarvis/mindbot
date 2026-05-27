#!/usr/bin/env python3
"""Example 14: hybrid memory recall with vector search.

This example demonstrates the Memory Recall Refactor path:

- write several memories into the four-tier memory store
- recall them through ``await MemoryManager.recall()``
- inspect ``MemoryHit`` score breakdowns
- build an LLM prompt with ``InputBuilder`` so recalled shards become
  per-shard ``ContextItem`` candidates for ``ContextPacker``

Run::

    python examples/14_vector_memory.py
    python examples/14_vector_memory.py --query "用户适合用什么语言做数据分析"
    python examples/14_vector_memory.py --real

``--real`` uses your configured ``~/.mindbot`` memory paths.  By default
the script uses a temporary directory so it does not pollute your real
memory store.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mindbot.agent.input_builder import InputBuilder
from mindbot.builders import create_embedder
from mindbot.config.loader import load_config
from mindbot.config.schema import ContextConfig
from mindbot.context.manager import ContextManager
from mindbot.memory.manager import MemoryManager, MemoryManagerConfig
from mindbot.memory.types import MemoryHit


DEMO_MEMORIES: tuple[tuple[str, str], ...] = (
    ("Python 是一种适合数据分析、自动化和机器学习的编程语言", "fact"),
    ("用户喜欢使用 VS Code 和深色主题写代码", "preference"),
    ("深度学习框架包括 PyTorch、TensorFlow 和 JAX", "fact"),
    ("Rust 语言适合需要内存安全和高性能的系统编程", "fact"),
    ("用户养了一只叫小花的橘猫，喜欢吃鱼", "preference"),
    ("Go 常用于微服务后端和云原生服务开发", "fact"),
    ("今天的会议讨论了 Kubernetes 集群扩缩容策略", "short_term"),
)


def build_demo_manager(*, use_real_store: bool) -> tuple[MemoryManager, tempfile.TemporaryDirectory[str] | None]:
    """Create a MemoryManager using either real config or an isolated temp dir."""
    config = load_config()
    if use_real_store:
        return MemoryManager.from_schema_config(config), None

    tmp = tempfile.TemporaryDirectory()
    memory_config = MemoryManagerConfig(
        base_path=str(Path(tmp.name) / "memory"),
        content_path=str(Path(tmp.name) / "memory" / "content"),
        vector_path=str(Path(tmp.name) / "vectors"),
        enable_vector=config.memory.vector.enabled,
        vector_dimension=config.memory.vector.dimension,
        default_agent_id="vector-demo",
        default_agent_name="VectorMemoryDemo",
    )
    embedder = None
    if memory_config.enable_vector:
        try:
            embedder = create_embedder(config)
        except Exception as exc:  # pragma: no cover - depends on user config
            print(f"[warn] could not build embedder from config: {exc}")
    return MemoryManager(config=memory_config, embedder=embedder), tmp


def seed_demo_memories(manager: MemoryManager) -> None:
    """Write a small set of memories for the recall demo."""
    for text, kind in DEMO_MEMORIES:
        if kind == "preference":
            manager.append_preference(text)
        elif kind == "short_term":
            manager.append_to_short_term(text)
        else:
            manager.promote_to_long_term(text)


def print_manager_status(manager: MemoryManager) -> None:
    """Show whether the vector layer and retriever are active."""
    stats = manager.get_stats()
    print("\n[Memory status]")
    print(f"  vector_enabled: {stats.get('vector_enabled')}")
    print(f"  vector_count:   {stats.get('vector_count', 'n/a')}")
    print(f"  retriever:      {type(manager._retriever).__name__ if manager._retriever else 'None'}")
    print(f"  embedder:       {type(manager._embedder).__name__ if manager._embedder else 'None'}")


def print_hit(hit: MemoryHit, index: int) -> None:
    """Pretty-print one MemoryHit with its signal breakdown."""
    shard = hit.shard
    print(f"\n[{index}] score={hit.score:.3f} reason={hit.reason}")
    print(
        "    "
        f"vector={hit.vector_score:.3f} "
        f"fts={hit.fts_score:.3f} "
        f"grep={hit.grep_score:.3f} "
        f"index={hit.index_score:.3f} "
        f"recency={hit.recency_score:.3f}"
    )
    print(f"    shard={shard.id[:8]} type={shard.shard_type.value} source={shard.source.value}")
    print(f"    text={shard.text[:120]}")


async def demo_recall(manager: MemoryManager, query: str, top_k: int) -> list[MemoryHit]:
    """Run hybrid recall and show explainable MemoryHit results."""
    print(f"\n[Recall] query={query!r} top_k={top_k}")
    started = time.perf_counter()
    hits = await manager.recall(query, top_k=top_k)
    elapsed_ms = (time.perf_counter() - started) * 1000

    print(f"  returned {len(hits)} hits in {elapsed_ms:.1f}ms")
    for index, hit in enumerate(hits, 1):
        print_hit(hit, index)
    return hits


async def demo_input_builder(manager: MemoryManager, query: str, top_k: int) -> None:
    """Build a prompt so recalled shards enter the ContextPacker individually."""
    context = ContextManager(ContextConfig(max_tokens=2000))
    builder = InputBuilder(
        context=context,
        memory=manager,
        memory_top_k=top_k,
        system_prompt="You are MindBot. Use recalled memory only when it is relevant.",
        response_reserve=256,
    )

    messages = await builder.build(query, intent_state="Answer using relevant recalled memory.")
    memory_messages = [
        msg for msg in messages
        if msg.role == "system"
        and isinstance(msg.content, str)
        and msg.content.startswith("- ")
    ]

    print("\n[InputBuilder]")
    print(f"  final_messages: {len(messages)}")
    print(f"  packed_memory_shards: {len(memory_messages)}")
    for index, msg in enumerate(memory_messages, 1):
        print(f"  memory[{index}]: {msg.content[:100]}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="MindBot hybrid memory recall demo")
    parser.add_argument(
        "--query",
        default="用户适合用什么语言做数据分析",
        help="Query used for memory recall.",
    )
    parser.add_argument("--top-k", type=int, default=4, help="Number of hits to recall.")
    parser.add_argument(
        "--real",
        action="store_true",
        help="Use configured ~/.mindbot memory instead of a temporary demo store.",
    )
    parser.add_argument(
        "--no-seed",
        action="store_true",
        help="Skip writing demo memories. Useful with --real.",
    )
    args = parser.parse_args()

    manager, tmp = build_demo_manager(use_real_store=args.real)
    try:
        print_manager_status(manager)
        if not args.no_seed:
            print("\n[Seed]")
            seed_demo_memories(manager)
            print(f"  wrote {len(DEMO_MEMORIES)} demo memories")

        await demo_recall(manager, args.query, args.top_k)
        await demo_input_builder(manager, args.query, args.top_k)
    finally:
        manager.close()
        if tmp is not None:
            tmp.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
