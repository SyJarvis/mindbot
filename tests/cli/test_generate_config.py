"""Tests for ``mindbot generate-config`` (template-driven workspace init).

Covers:
- First-run creates settings.json and SYSTEM.md from templates
- Created files contain expected content
- Workspace sub-directories are created
- Overwrite prompt respected (simulated)
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from mindbot.cli import _read_template


def test_read_template_settings():
    text = _read_template("settings.example.json")
    assert "agent" in text
    assert "providers" in text


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
    assert (root / "settings.json").exists()
    assert (root / "SYSTEM.md").exists()
    assert (root / "skills").is_dir()
    assert (root / "memory").is_dir()
    assert (root / "history").is_dir()
    assert (root / "cron").is_dir()
    assert (root / "workspace").is_dir()

    settings_content = (root / "settings.json").read_text(encoding="utf-8")
    assert "agent" in settings_content
    assert '"workspace": "~/.mindbot/workspace"' in settings_content
    assert '"system_path_whitelist"' in settings_content
    assert '"trusted_paths"' in settings_content
    assert '"shell_execution"' in settings_content

    system_content = (root / "SYSTEM.md").read_text(encoding="utf-8")
    assert len(system_content) > 0


def test_generate_config_overwrite_declined(tmp_path, monkeypatch):
    """When user declines overwrite, files remain unchanged."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

    root = fake_home / ".mindbot"
    root.mkdir(parents=True)
    settings = root / "settings.json"
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
    (root / "settings.json").write_text("old", encoding="utf-8")
    (root / "SYSTEM.md").write_text("old", encoding="utf-8")

    from typer.testing import CliRunner
    from mindbot.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["generate-config"], input="y\n")

    assert result.exit_code == 0
    assert (root / "settings.json").read_text(encoding="utf-8") != "old"
    assert (root / "SYSTEM.md").read_text(encoding="utf-8") != "old"


def test_update_settings_model(tmp_path):
    """Test _update_settings_model updates both agent.model and providers."""
    from mindbot.cli import _update_settings_model

    config_file = tmp_path / "settings.json"
    config_file.write_text(
        '{"providers": {"local-ollama": {"endpoints": [{"models": [{"id": "old-model"}]}]}}}',
        encoding="utf-8",
    )

    _update_settings_model(config_file, "qwen3:2b")

    content = config_file.read_text(encoding="utf-8")
    data = json.loads(content)

    # agent.model should be full format
    assert data["agent"]["model"] == "local-ollama/qwen3:2b"

    # providers model id should be updated
    assert data["providers"]["local-ollama"]["endpoints"][0]["models"][0]["id"] == "qwen3:2b"


def test_update_settings_model_vision_detection(tmp_path):
    """Test _update_settings_model sets vision=true for VL models."""
    from mindbot.cli import _update_settings_model

    config_file = tmp_path / "settings.json"
    config_file.write_text('{}', encoding="utf-8")

    _update_settings_model(config_file, "qwen3-vl:8b")

    content = config_file.read_text(encoding="utf-8")
    data = json.loads(content)

    # vision should be true for vl model
    assert data["providers"]["local-ollama"]["endpoints"][0]["models"][0]["vision"] == True


def test_update_settings_model_creates_agent_section(tmp_path):
    """Test _update_settings_model creates agent and providers sections if missing."""
    from mindbot.cli import _update_settings_model

    config_file = tmp_path / "settings.json"
    config_file.write_text('{}', encoding="utf-8")

    _update_settings_model(config_file, "llama3:8b")

    content = config_file.read_text(encoding="utf-8")
    data = json.loads(content)

    assert "agent" in data
    assert data["agent"]["model"] == "local-ollama/llama3:8b"
    assert "providers" in data
    assert "local-ollama" in data["providers"]


def test_list_local_models_parses_output(monkeypatch):
    """Test list_local_models parses ollama list output."""
    from mindbot.utils.ollama_setup import OllamaSetup
    from unittest.mock import patch

    mock_output = "NAME                ID              SIZE      MODIFIED\nqwen3:2b            abc123          1.2 GB    2 days ago\nllama3:8b           def456          4.7 GB    1 week ago"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = mock_output
        setup = OllamaSetup()
        models = setup.list_local_models()

        assert len(models) == 2
        assert models[0]["name"] == "qwen3:2b"
        assert models[0]["size"] == "1.2"
        assert models[1]["name"] == "llama3:8b"


def test_list_local_models_empty(monkeypatch):
    """Test list_local_models returns empty list when no models."""
    from mindbot.utils.ollama_setup import OllamaSetup
    from unittest.mock import patch

    mock_output = "NAME                ID              SIZE      MODIFIED"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = mock_output
        setup = OllamaSetup()
        models = setup.list_local_models()

        assert models == []


def test_generate_config_skip_ollama(tmp_path, monkeypatch):
    """Test generate-config with --skip-ollama skips ollama checks."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

    from typer.testing import CliRunner
    from mindbot.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["generate-config", "--skip-ollama"])

    assert result.exit_code == 0
    # Should not contain Ollama related output
    assert "Ollama" not in result.output or "Skipping" in result.output
