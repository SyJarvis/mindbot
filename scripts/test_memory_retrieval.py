#!/usr/bin/env python3
"""
Test script for long-term memory retrieval functionality.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mindbot.memory.manager import MemoryManager
from mindbot.context.manager import ContextManager
from mindbot.agent.input_builder import InputBuilder


async def test_memory_indexing():
    """Test indexing long-term directory."""
    print("=" * 60)
    print("Test 1: Indexing long-term directory")
    print("=" * 60)

    memory = MemoryManager(
        storage_path="~/.mindbot/data/memory.db",
        markdown_path="~/.mindbot/data/memory",
    )

    # Index the long-term directory
    count = memory.index_long_term_directory(force_reindex=False)
    print(f"\nIndexed {count} chunks")

    # Search for something
    query = "毕业实习手册的材料装订顺序"
    print(f"\nRecalling for: {query}")

    hits = await memory.recall(query, top_k=3)
    print(f"Found {len(hits)} hits:")

    for i, hit in enumerate(hits, 1):
        chunk = hit.shard
        print(f"\n--- Result {i} (score={hit.score:.3f} reason={hit.reason}) ---")
        print(f"Source: {chunk.source.value}")
        print(f"Text preview: {chunk.text[:200]}...")

    memory.close()


async def test_input_builder():
    """Test InputBuilder with long-term memory."""
    print("\n" + "=" * 60)
    print("Test 2: InputBuilder with long-term memory")
    print("=" * 60)

    memory = MemoryManager(
        storage_path="~/.mindbot/data/memory.db",
        markdown_path="~/.mindbot/data/memory",
    )

    context = ContextManager(max_tokens=8000)

    builder = InputBuilder(
        context,
        memory=memory,
        memory_top_k=3,
    )

    # Build input with a query
    query = "毕业实习报告的格式要求有哪些？"
    print(f"\nBuilding input for query: {query}")

    messages = await builder.build(query)
    print(f"\nGenerated {len(messages)} messages")

    # Find memory block messages
    memory_messages = [m for m in messages if "Relevant context from memory" in m.text]
    if memory_messages:
        print(f"\nMemory block found ({len(memory_messages)} messages):")
        for msg in memory_messages:
            print(f"\n{msg.text[:500]}...")
    else:
        print("\nNo memory block found")

    # Check context blocks
    memory_block = context.get_block("memory")
    print(f"\nMemory block: {memory_block.token_count} tokens, {len(memory_block.messages)} messages")

    memory.close()


async def test_retrieval_strategies():
    """Test different retrieval strategies."""
    print("\n" + "=" * 60)
    print("Test 3: Retrieval strategies comparison")
    print("=" * 60)

    memory = MemoryManager(
        storage_path="~/.mindbot/data/memory.db",
        markdown_path="~/.mindbot/data/memory",
    )

    queries = [
        "毕业实习手册的材料装订顺序",
        "实习报告字体要求",
        "实习记录需要填写几次",
    ]

    for query in queries:
        print(f"\nQuery: {query}")

        hits = await memory.recall(query, top_k=3)
        print(f"  Recalled: {len(hits)} hits")
        for hit in hits:
            chunk = hit.shard
            print(
                f"    - [{chunk.source.value}] score={hit.score:.3f}"
                f" ({hit.reason}) :: {chunk.text[:80]}..."
            )

    memory.close()


async def main():
    """Run all tests."""
    try:
        await test_memory_indexing()
        await test_input_builder()
        await test_retrieval_strategies()
        print("\n" + "=" * 60)
        print("All tests completed!")
        print("=" * 60)
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
