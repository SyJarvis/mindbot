"""Tests for ``mindbot generate-config`` (template-driven workspace init).

Covers:
- First-run creates settings.yaml and SYSTEM.md from templates
- Created files contain expected content
- Workspace sub-directories are created
- Overwrite prompt respected (simulated)
"""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from mindbot.cli import _read_template


def test_read_template_settings():
    text = _read_template("settings.example.yaml")
    assert "agent:" in text
    assert "providers:" in text


def test_read_template_system():
    text = _read_template("SYSTEM.md")
    assert "Mindbot" in text or "mindbot" in text.lower()


def test_generate_config_creates_files(tmp_path, monkeypatch):
    """First-run creates both files and sub-directories."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

    from typer.testing import CliRunner
    from mindbot.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["generate-config"])

    assert result.exit_code == 0

    root = fake_home / ".mindbot"
    assert (root / "settings.yaml").exists()
    assert (root / "SYSTEM.md").exists()
    assert (root / "skills").is_dir()
    assert (root / "memory").is_dir()
    assert (root / "history").is_dir()

    settings_content = (root / "settings.yaml").read_text(encoding="utf-8")
    assert "agent:" in settings_content

    system_content = (root / "SYSTEM.md").read_text(encoding="utf-8")
    assert len(system_content) > 0


def test_generate_config_overwrite_declined(tmp_path, monkeypatch):
    """When user declines overwrite, files remain unchanged."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

    root = fake_home / ".mindbot"
    root.mkdir(parents=True)
    settings = root / "settings.yaml"
    settings.write_text("original", encoding="utf-8")

    from typer.testing import CliRunner
    from mindbot.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["generate-config"], input="n\n")

    assert settings.read_text(encoding="utf-8") == "original"


def test_generate_config_overwrite_accepted(tmp_path, monkeypatch):
    """When user confirms overwrite, both files are replaced."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

    root = fake_home / ".mindbot"
    root.mkdir(parents=True)
    (root / "settings.yaml").write_text("old", encoding="utf-8")
    (root / "SYSTEM.md").write_text("old", encoding="utf-8")

    from typer.testing import CliRunner
    from mindbot.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["generate-config"], input="y\n")

    assert result.exit_code == 0
    assert (root / "settings.yaml").read_text(encoding="utf-8") != "old"
    assert (root / "SYSTEM.md").read_text(encoding="utf-8") != "old"
