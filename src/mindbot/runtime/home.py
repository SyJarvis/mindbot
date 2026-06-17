"""Runtime home bootstrap."""

from __future__ import annotations

from pathlib import Path

from mindbot.config.schema import Config


def ensure_runtime_home(config: Config) -> None:
    """Create MindBot runtime directories without writing user config files."""
    root = Path.home() / ".mindbot"
    directories = {
        root,
        _dir_path(config.agent.workspace),
        _dir_path(config.memory.base_path),
        _dir_path(config.memory.content_path),
        _dir_path(config.memory.markdown_path),
        _dir_path(config.memory.vector.persist_path),
        _dir_path(config.session_journal.path),
        _file_parent(config.memory.storage_path),
        root / "cron",
        root / "data",
        root / "history",
        root / "logs",
        root / "skills",
        root / "tools",
    }

    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)


def _dir_path(value: str) -> Path:
    return _expand_home(value)


def _file_parent(value: str) -> Path:
    return _expand_home(value).parent


def _expand_home(value: str) -> Path:
    if value == "~":
        return Path.home()
    if value.startswith("~/"):
        return Path.home() / value[2:]
    return Path(value).expanduser()
