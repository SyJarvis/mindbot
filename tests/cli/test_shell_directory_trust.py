from __future__ import annotations

import json
from pathlib import Path

import pytest

from mindbot.cli import (
    _ShellSessionContext,
    _build_shell_turn_tools,
    _persist_trusted_path,
    _prompt_trust_session_cwd,
    _resolve_shell_session_context,
)
from mindbot.config.schema import Config


class _FakeBot:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.model = config.agent.model
        self.provider = "openai"

    def list_tools(self) -> list[object]:
        return []


def _write_config(config_file: Path, workspace: Path) -> None:
    config_file.write_text(
        json.dumps(
            {
                "providers": {
                    "openai": {
                        "type": "openai",
                        "endpoints": [
                            {
                                "base_url": "https://example.com",
                                "models": [{"id": "test", "role": "chat", "vision": False}],
                            }
                        ],
                    }
                },
                "agent": {
                    "model": "openai/test",
                    "workspace": str(workspace),
                    "system_path_whitelist": [],
                    "trusted_paths": [],
                },
            }
        ),
        encoding="utf-8",
    )


def test_resolve_shell_session_context_marks_workspace_as_authorized(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config_file = tmp_path / "settings.json"
    _write_config(config_file, workspace)
    bot = _FakeBot(Config(agent={"model": "openai/test", "workspace": str(workspace)}))

    shell_ctx = _resolve_shell_session_context(bot, config_file, workspace)

    assert shell_ctx.session_cwd == workspace
    assert shell_ctx.session_cwd_authorized is True
    assert shell_ctx.effective_root == workspace


def test_persist_trusted_path_updates_config_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    trusted = tmp_path / "project"
    trusted.mkdir()
    config_file = tmp_path / "settings.json"
    _write_config(config_file, workspace)

    _persist_trusted_path(config_file, trusted)

    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert data["agent"]["trusted_paths"] == [str(trusted)]


def test_prompt_trust_session_cwd_allows_session_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    current_dir = tmp_path / "project"
    current_dir.mkdir()
    config_file = tmp_path / "settings.json"
    _write_config(config_file, workspace)
    bot = _FakeBot(Config(agent={"model": "openai/test", "workspace": str(workspace)}))
    shell_ctx = _ShellSessionContext(
        config_file=config_file,
        workspace=workspace,
        session_cwd=current_dir,
        session_cwd_authorized=None,
    )
    monkeypatch.setattr("mindbot.cli.typer.prompt", lambda *args, **kwargs: "session")

    _prompt_trust_session_cwd(bot, shell_ctx)

    assert shell_ctx.session_cwd_authorized is True
    assert current_dir in shell_ctx.session_trusted_paths
    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert data["agent"]["trusted_paths"] == []


def test_build_shell_turn_tools_prefers_authorized_session_cwd(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "workspace.txt").write_text("workspace", encoding="utf-8")
    current_dir = tmp_path / "project"
    current_dir.mkdir()
    (current_dir / "current.txt").write_text("current", encoding="utf-8")
    config_file = tmp_path / "settings.json"
    _write_config(config_file, workspace)
    bot = _FakeBot(Config(agent={"model": "openai/test", "workspace": str(workspace)}))
    shell_ctx = _ShellSessionContext(
        config_file=config_file,
        workspace=workspace,
        session_cwd=current_dir,
        session_trusted_paths={current_dir},
        session_cwd_authorized=True,
    )

    tools = {tool.name: tool for tool in _build_shell_turn_tools(bot, shell_ctx)}
    listing = tools["list_directory"].handler(".")  # type: ignore[union-attr]

    assert "[FILE] current.txt" in listing
    assert "workspace.txt" not in listing


def test_build_shell_turn_tools_falls_back_to_workspace_when_denied(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "workspace.txt").write_text("workspace", encoding="utf-8")
    current_dir = tmp_path / "project"
    current_dir.mkdir()
    (current_dir / "current.txt").write_text("current", encoding="utf-8")
    config_file = tmp_path / "settings.json"
    _write_config(config_file, workspace)
    bot = _FakeBot(Config(agent={"model": "openai/test", "workspace": str(workspace)}))
    shell_ctx = _ShellSessionContext(
        config_file=config_file,
        workspace=workspace,
        session_cwd=current_dir,
        session_cwd_authorized=False,
    )

    tools = {tool.name: tool for tool in _build_shell_turn_tools(bot, shell_ctx)}
    listing = tools["list_directory"].handler(".")  # type: ignore[union-attr]

    assert "[FILE] workspace.txt" in listing
    assert "current.txt" not in listing
