#!/usr/bin/env python3
"""Seed memory data into ~/.mindbot for testing.

Usage:
    python examples/seed_memory.py          # 写入 demo 记忆
    python examples/seed_memory.py --clear  # 先清除已有记忆
    python examples/seed_memory.py --show   # 只查看当前状态
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mindbot.config.loader import load_config
from mindbot.memory.manager import MemoryManager


DEMO_MEMORIES = (
    # (content, method, description)
    # ("用户是一名全栈工程师，擅长 Python 和 TypeScript", "promote_to_long_term", "用户画像"),
    ("用户喜欢用 VS Code 开发，主题是 One Dark Pro", "append_preference", "开发偏好"),
    ("用户养了一只叫小花的橘猫", "append_preference", "个人偏好"),
    ("项目使用 FastAPI + Pydantic v2 技术栈", "promote_to_long_term", "技术栈"),
    ("用户偏好中文交流，技术术语可用英文", "append_preference", "语言偏好"),
    ("用户正在进行 Memory 系统的开发和测试", "append_to_short_term", "当前任务"),
    ("Python 的 asyncio 是项目核心依赖", "promote_to_long_term", "知识库"),
    ("LanceDB 用于向量存储和混合检索", "promote_to_long_term", "知识库"),
    ("用户的名字叫上邪", "promote_to_long_term", "用户画像-姓名"),
    ("用户性别男", "promote_to_long_term", "用户画像-性别"),
    ("用户26岁，出生于2000年02月20日", "promote_to_long_term", "用户画像-年龄生日"),
    ("用户身高180cm", "promote_to_long_term", "用户画像-身高"),
    ("用户体重70kg", "promote_to_long_term", "用户画像-体重"),
    ("用户喜欢写代码", "append_preference", "用户画像-爱好"),
)


def seed(manager: MemoryManager) -> None:
    """Write demo memories."""
    print("[Seed] 写入记忆数据...")
    for content, method, desc in DEMO_MEMORIES:
        fn = getattr(manager, method)
        fn(content)
        print(f"  [{method}] {desc}: {content}")
    print(f"\n共写入 {len(DEMO_MEMORIES)} 条记忆")


def show_status(manager: MemoryManager) -> None:
    """Print current memory status."""
    stats = manager.get_stats()
    print("[Memory Status]")
    for k, v in stats.items():
        print(f"  {k}: {v}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed MindBot memory for testing")
    parser.add_argument("--clear", action="store_true", help="Clear existing memory before seeding")
    parser.add_argument("--show", action="store_true", help="Only show current status, no seeding")
    args = parser.parse_args()

    config = load_config()
    manager = MemoryManager.from_schema_config(config)

    try:
        show_status(manager)

        if args.show:
            return

        if args.clear:
            print("\n[Clear] 清除已有记忆...")
            report = manager.run_forget_cycle()
            print(f"  deleted: {len(report.deleted)}, archived: {len(report.archived)}")

        print()
        seed(manager)

        print()
        show_status(manager)
    finally:
        manager.close()


if __name__ == "__main__":
    main()
