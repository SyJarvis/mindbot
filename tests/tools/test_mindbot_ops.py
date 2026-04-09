from __future__ import annotations

import json
from pathlib import Path

from mindbot.tools.mindbot_ops import create_mindbot_tools


def test_runtime_info_reports_workspace_policy(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    mindbot_home = home / ".mindbot"
    workspace = mindbot_home / "workspace"
    workspace.mkdir(parents=True)
    (mindbot_home / "SYSTEM.md").write_text("system prompt", encoding="utf-8")
    (mindbot_home / "settings.json").write_text(
        """
        {
          "agent": {
            "model": "openai/test",
            "workspace": "~/.mindbot/workspace",
            "system_path_whitelist": ["~/.mindbot"],
            "trusted_paths": ["~/trusted-project"],
            "restrict_to_workspace": true,
            "shell_execution": {
              "policy": "cwd_guard",
              "sandbox_provider": "none",
              "fail_if_unavailable": false
            }
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("MIND_CONFIG_PATH", raising=False)

    trusted_project = home / "trusted-project"
    trusted_project.mkdir()

    tools = create_mindbot_tools(
        workspace,
        allowed_paths=[mindbot_home, trusted_project],
        session_cwd=trusted_project,
        effective_workspace=trusted_project,
        session_trusted_paths=[trusted_project],
        session_cwd_authorized=True,
    )
    payload = tools[0].handler()  # type: ignore[union-attr]
    data = json.loads(payload)

    assert data["config"]["configured_workspace"] == str(workspace)
    assert data["config"]["restrict_to_workspace"] is True
    assert data["config"]["system_path_whitelist"] == [str(mindbot_home)]
    assert data["config"]["trusted_paths"] == [str(trusted_project)]
    assert data["config"]["shell_execution"]["policy"] == "cwd_guard"
    assert data["config"]["shell_execution"]["sandbox_provider"] == "none"
    assert data["system"]["workspace"] == str(workspace)
    assert data["system"]["effective_workspace"] == str(trusted_project)
    assert data["system"]["session_cwd"] == str(trusted_project)
    assert data["system"]["session_cwd_authorized"] is True
    assert data["system"]["session_trusted_paths"] == [str(trusted_project)]
    assert str(mindbot_home) in data["system"]["allowed_paths"]
    assert data["system"]["allowed_path_policy"] == "Each allowed path grants access to that directory tree."
    assert "does not provide OS-level shell sandboxing" in data["system"]["shell_execution_boundary"]
    assert "cwd" not in data["system"]
