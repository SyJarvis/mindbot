"""ACP channel configuration models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ACPAgentConfig(BaseModel):
    """Configuration for a single ACP agent."""

    name: str = Field(description="Display name for this agent")
    command: str = Field(description="Command to spawn the agent (e.g. 'npx')")
    args: list[str] = Field(default_factory=list, description="Arguments (e.g. ['--acp'])")
    cwd: str | None = Field(default=None, description="Working directory for the agent")
    env: dict[str, str] = Field(default_factory=dict, description="Extra environment variables")
    timeout: int = Field(default=300, description="Prompt timeout in seconds")
    max_sessions: int = Field(default=100, description="Max concurrent sessions per agent")


class ACPPermissionPolicy(BaseModel):
    """Permission policy for ACP agent requests."""

    auto_approve_kinds: list[str] = Field(
        default_factory=lambda: ["read", "search"],
        description="Tool kinds to auto-approve",
    )
    allow_paths: list[str] = Field(
        default_factory=list,
        description="Directory roots the agent is allowed to access",
    )
    interactive: bool = Field(
        default=False,
        description="Prompt user for approval via chat platform (future)",
    )


class ACPChannelConfig(BaseModel):
    """ACP channel configuration."""

    enabled: bool = False
    agents: dict[str, ACPAgentConfig] = Field(
        default_factory=dict,
        description="Named ACP agent configurations",
    )
    default_agent: str | None = Field(
        default=None,
        description="Default agent name for unconfigured chats",
    )
    permission_policy: ACPPermissionPolicy = Field(
        default_factory=ACPPermissionPolicy,
    )
    session_idle_timeout: int = Field(
        default=3600,
        description="Idle session cleanup timeout in seconds",
    )
    routing: dict[str, str] = Field(
        default_factory=dict,
        description="Map chat_id patterns to agent names",
    )
    show_label: bool = Field(
        default=True,
        description="Prepend agent name to responses (e.g. '[Claude Code] ...')",
    )
