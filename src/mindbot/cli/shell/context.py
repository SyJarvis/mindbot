"""Shell 会话上下文：信任状态、权限管理、工具构建。"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Console

console = Console()


@dataclass
class ShellSessionContext:
    """Per-session shell directory and trust state."""

    config_file: Path | None
    workspace: Path
    session_cwd: Path
    session_id: str = "default"
    persisted_trusted_paths: set[Path] = field(default_factory=set)
    session_trusted_paths: set[Path] = field(default_factory=set)
    session_cwd_authorized: bool | None = None
    permission_manager: Any | None = None

    @property
    def trusted_paths(self) -> list[Path]:
        return sorted(self.persisted_trusted_paths | self.session_trusted_paths)

    @property
    def effective_root(self) -> Path:
        return self.session_cwd if self.session_cwd_authorized else self.workspace

    @property
    def trust_status(self) -> str:
        if self.session_cwd_authorized is True:
            if self.session_cwd == self.workspace:
                return "workspace"
            return "authorized"
        if self.session_cwd_authorized is False:
            return "denied"
        return "pending"


def unique_paths(paths: list[Path | str]) -> list[Path]:
    """去重并规范化路径列表。"""
    resolved: list[Path] = []
    for path in paths:
        candidate = Path(path).expanduser().resolve()
        if candidate not in resolved:
            resolved.append(candidate)
    return resolved


def resolve_shell_session_context(bot: Any, config_file: Path | None, launch_cwd: Path) -> ShellSessionContext:
    """根据配置和启动目录构建 shell 会话状态。"""
    from mindbot.tools.path_policy import is_within_allowed_roots, resolve_allowed_roots

    workspace, allowed_roots = resolve_allowed_roots(
        bot.config.agent.workspace,
        restrict_to_workspace=bot.config.agent.restrict_to_workspace,
        allowed_paths=[
            *bot.config.agent.system_path_whitelist,
            *bot.config.agent.trusted_paths,
        ],
    )
    session_cwd = launch_cwd.expanduser().resolve()
    persisted_trusted_paths = set(unique_paths(list(bot.config.agent.trusted_paths)))
    # 仅当在允许根目录内时预授权，否则留 None 以触发用户确认
    pre_authorized = is_within_allowed_roots(session_cwd, allowed_roots)
    return ShellSessionContext(
        config_file=config_file,
        workspace=workspace,
        session_cwd=session_cwd,
        persisted_trusted_paths=persisted_trusted_paths,
        session_cwd_authorized=True if pre_authorized else None,
    )


def persist_trusted_path(config_file: Path | None, trusted_path: Path) -> None:
    """将受信路径持久化到配置文件。"""
    if config_file is None:
        return
    data = json.loads(config_file.read_text(encoding="utf-8"))
    agent_data = data.setdefault("agent", {})
    trusted_paths = agent_data.setdefault("trusted_paths", [])
    trusted_text = str(trusted_path)
    if trusted_text not in trusted_paths:
        trusted_paths.append(trusted_text)
        config_file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


async def prompt_trust_session_cwd_with_natural_language(
    permission_manager: Any,
    shell_ctx: ShellSessionContext,
) -> bool:
    """使用自然语言对话框询问目录信任。

    Returns:
        True 表示已授权，False 表示拒绝。
    """
    from datetime import datetime

    from mindbot.permissions import (
        PermissionRequest,
        PermissionType,
        PermissionGrant,
    )
    from prompt_toolkit.shortcuts import radiolist_dialog

    # 检查是否已授权
    is_granted, _ = permission_manager.check_permission(
        PermissionType.DIRECTORY_ACCESS,
        str(shell_ctx.session_cwd),
    )
    if is_granted:
        shell_ctx.session_cwd_authorized = True
        return True

    # 创建权限请求
    request = PermissionRequest(
        request_id=str(uuid.uuid4()),
        permission_type=PermissionType.DIRECTORY_ACCESS,
        resource=str(shell_ctx.session_cwd),
        context={
            "path": str(shell_ctx.session_cwd),
            "workspace": str(shell_ctx.workspace),
            "action": "访问并作为当前工作目录",
        },
        reason=f"当前目录 {shell_ctx.session_cwd} 在工作目录 {shell_ctx.workspace} 之外",
        risk_level="low",
    )

    # 交互式选择对话框
    path = str(shell_ctx.session_cwd)
    workspace = str(shell_ctx.workspace)
    result = await radiolist_dialog(
        title="⚠️ 目录访问权限请求",
        text=(
            f"MindBot 需要 访问并作为当前工作目录以下目录:\n"
            f"  {path}\n\n"
            f"原因: 当前目录 {path} 在工作目录 {workspace} 之外"
        ),
        values=[
            ("session", "本次允许"),
            ("always",  "永久允许（推荐）"),
            ("deny",    "拒绝访问"),
        ],
        default="always",
    ).run_async()

    # 用户取消（Esc）→ 视为拒绝
    if result is None:
        result = "deny"

    # 处理决定
    if result == "session":
        permission_manager.add_session_grant(PermissionGrant(
            resource=str(shell_ctx.session_cwd),
            permission_type=PermissionType.DIRECTORY_ACCESS,
            scope="session",
            granted_at=datetime.now(),
        ))
        shell_ctx.session_trusted_paths.add(shell_ctx.session_cwd)
        shell_ctx.session_cwd_authorized = True
        console.print(f"[green]已授权本次会话访问:[/green] {path}")
        return True

    elif result == "always":
        permission_manager.add_session_grant(PermissionGrant(
            resource=str(shell_ctx.session_cwd),
            permission_type=PermissionType.DIRECTORY_ACCESS,
            scope="persistent",
            granted_at=datetime.now(),
        ))
        permission_manager._persist_grant(request)
        shell_ctx.persisted_trusted_paths.add(shell_ctx.session_cwd)
        shell_ctx.session_cwd_authorized = True
        console.print(f"[green]已永久授权访问:[/green] {path}")
        return True

    else:  # deny
        shell_ctx.session_cwd_authorized = False
        console.print(
            f"[yellow]目录未授权.[/yellow] MindBot 将继续使用工作目录 {workspace}"
        )
        return False


def build_shell_turn_tools(bot: Any, shell_ctx: ShellSessionContext) -> list[Any]:
    """根据当前信任状态构建工具集。"""
    from mindbot.tools.file_ops import create_file_tools
    from mindbot.tools.mindbot_ops import create_mindbot_tools
    from mindbot.tools.shell_ops import create_shell_tools
    from mindbot.tools.web_ops import create_web_tools

    allowed_paths = unique_paths(
        [
            shell_ctx.workspace,
            *bot.config.agent.system_path_whitelist,
            *bot.config.agent.trusted_paths,
            *[str(path) for path in shell_ctx.session_trusted_paths],
        ]
    )
    effective_root = shell_ctx.effective_root

    file_tools = create_file_tools(
        effective_root,
        restrict_to_workspace=bot.config.agent.restrict_to_workspace,
        allowed_paths=allowed_paths,
    )
    shell_tools = create_shell_tools(
        effective_root,
        restrict_to_workspace=bot.config.agent.restrict_to_workspace,
        allowed_paths=allowed_paths,
        execution_policy=bot.config.agent.shell_execution.policy.value,
        sandbox_provider=bot.config.agent.shell_execution.sandbox_provider.value,
        fail_if_unavailable=bot.config.agent.shell_execution.fail_if_unavailable,
        block_dangerous_commands=bot.config.agent.shell_execution.block_dangerous_commands,
    )
    mindbot_tools = create_mindbot_tools(
        shell_ctx.workspace,
        restrict_to_workspace=bot.config.agent.restrict_to_workspace,
        allowed_paths=allowed_paths,
        session_cwd=shell_ctx.session_cwd,
        effective_workspace=effective_root,
        session_trusted_paths=shell_ctx.trusted_paths,
        session_cwd_authorized=shell_ctx.session_cwd_authorized,
    )
    web_tools = create_web_tools()

    merged: dict[str, Any] = {}
    builtin_names: set[str] = set()
    for tool in [*file_tools, *shell_tools, *mindbot_tools, *web_tools]:
        merged[tool.name] = tool
        builtin_names.add(tool.name)

    for tool in bot.list_tools():
        tool_name = getattr(tool, "name", type(tool).__name__)
        if tool_name not in builtin_names:
            merged[tool_name] = tool

    return list(merged.values())
