"""CLI 共享工具函数与全局对象。"""

from pathlib import Path

from rich.console import Console

# 共享 console 实例
console = Console()


def find_config_file() -> Path | None:
    """查找活跃的配置文件（仅 JSON）。"""
    root = Path.home() / ".mindbot"
    json_file = root / "settings.json"
    if json_file.exists():
        return json_file
    return None
