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
            "restrict_to_workspace": true
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("MIND_CONFIG_PATH", raising=False)

    tools = create_mindbot_tools(workspace, allowed_paths=[mindbot_home])
    payload = tools[0].handler()  # type: ignore[union-attr]
    data = json.loads(payload)

    assert data["config"]["configured_workspace"] == str(workspace)
    assert data["config"]["restrict_to_workspace"] is True
    assert data["config"]["system_path_whitelist"] == [str(mindbot_home)]
    assert data["system"]["workspace"] == str(workspace)
    assert str(mindbot_home) in data["system"]["allowed_paths"]
    assert "cwd" not in data["system"]
