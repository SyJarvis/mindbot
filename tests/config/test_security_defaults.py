from __future__ import annotations

from mindbot.config.schema import Config, ToolAskMode, ToolSecurityLevel


def test_default_agent_security_allows_full_access() -> None:
    config = Config()

    assert config.agent.approval.security == ToolSecurityLevel.FULL
    assert config.agent.approval.ask == ToolAskMode.OFF
    assert config.agent.restrict_to_workspace is False
    assert config.agent.shell_execution.block_dangerous_commands is False


def test_agent_security_can_still_be_restricted() -> None:
    config = Config(
        agent={
            "approval": {"security": "allowlist", "ask": "on_miss"},
            "restrict_to_workspace": True,
            "shell_execution": {"block_dangerous_commands": True},
        }
    )

    assert config.agent.approval.security == ToolSecurityLevel.ALLOWLIST
    assert config.agent.approval.ask == ToolAskMode.ON_MISS
    assert config.agent.restrict_to_workspace is True
    assert config.agent.shell_execution.block_dangerous_commands is True
