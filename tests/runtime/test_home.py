from __future__ import annotations

from pathlib import Path

from mindbot.config.schema import Config
from mindbot.runtime import ensure_runtime_home


def test_ensure_runtime_home_creates_runtime_dirs(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    ensure_runtime_home(Config())

    root = home / ".mindbot"
    expected_dirs = [
        root,
        root / "workspace",
        root / "data",
        root / "data" / "memory",
        root / "data" / "journal",
        root / "memory",
        root / "memory" / "content",
        root / "vectors",
        root / "logs",
        root / "history",
        root / "cron",
        root / "tools",
        root / "skills",
    ]

    for directory in expected_dirs:
        assert directory.is_dir()

    assert not (root / "history" / "cli_history").exists()
    assert not (root / "settings.json").exists()
    assert not (root / "SYSTEM.md").exists()


def test_ensure_runtime_home_accepts_existing_cli_history_file(tmp_path, monkeypatch):
    home = tmp_path / "home"
    history_dir = home / ".mindbot" / "history"
    history_dir.mkdir(parents=True)
    (history_dir / "cli_history").write_text("old history\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    ensure_runtime_home(Config())

    assert (history_dir / "cli_history").is_file()


def test_mindbot_bootstrap_without_settings_file(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    from mindbot.bot import MindBot

    bot = MindBot()

    assert bot.config is not None
    assert (home / ".mindbot" / "workspace").is_dir()
    assert (home / ".mindbot" / "cron").is_dir()
    assert not (home / ".mindbot" / "settings.json").exists()
