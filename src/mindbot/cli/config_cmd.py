"""MindBot 实时配置系统 CLI 命令

使用方法:
    mindbot config --help
    mindbot config get <scope> <key>
    mindbot config set <scope> <key> <value>
    mindbot config auth grant <user_id> <tool_name> [--expires <seconds>]
    mindbot config auth revoke <user_id> <tool_name>
    mindbot config auth check <user_id> <tool_name>
    mindbot config list [<scope>]
    mindbot config demo
"""

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from mindbot.config.bus import ConfigBus
from mindbot.auth.manager import AuthManager
from mindbot.config.persistence import ConfigPersistence
from mindbot.config.integration import AgentConfigIntegration

app = typer.Typer(help="实时配置系统管理")
console = Console()

# 全局状态（在 shell 模式下共享）
_config_integration: Optional[AgentConfigIntegration] = None


def get_integration() -> AgentConfigIntegration:
    """获取或创建配置集成实例"""
    global _config_integration
    if _config_integration is None:
        persistence_path = Path.home() / ".mindbot" / "config_store.json"
        _config_integration = AgentConfigIntegration(
            persistence_path=persistence_path,
            enable_persistence=True,
        )
    return _config_integration


async def init_integration():
    """异步初始化配置集成"""
    integration = get_integration()
    await integration.initialize()
    return integration


@app.command("get")
def config_get(
    scope: str = typer.Argument(..., help="配置作用域，如: global, user:123"),
    key: str = typer.Argument(..., help="配置键名"),
):
    """获取配置值"""
    async def _get():
        integration = await init_integration()
        value = await integration.get(scope, key)
        if value is not None:
            console.print(f"[green]{scope}.{key} = {value}[/green]")
        else:
            console.print(f"[yellow]{scope}.{key} = (未设置)[/yellow]")

    asyncio.run(_get())


@app.command("set")
def config_set(
    scope: str = typer.Argument(..., help="配置作用域"),
    key: str = typer.Argument(..., help="配置键名"),
    value: str = typer.Argument(..., help="配置值"),
):
    """设置配置值（立即生效）"""
    async def _set():
        integration = await init_integration()
        await integration.set(scope, key, value)
        console.print(f"[green]✓ 已设置: {scope}.{key} = {value}[/green]")

    asyncio.run(_set())


@app.command("delete")
def config_delete(
    scope: str = typer.Argument(..., help="配置作用域"),
    key: str = typer.Argument(..., help="配置键名"),
):
    """删除配置值"""
    async def _delete():
        integration = await init_integration()
        result = await integration.bus.delete(scope, key)
        if result:
            console.print(f"[green]✓ 已删除: {scope}.{key}[/green]")
        else:
            console.print(f"[yellow]✗ 未找到: {scope}.{key}[/yellow]")

    asyncio.run(_delete())


@app.command("list")
def config_list(
    scope: Optional[str] = typer.Argument(None, help="配置作用域（可选）"),
):
    """列出配置"""
    async def _list():
        integration = await init_integration()

        table = Table(title="实时配置")
        table.add_column("Scope", style="cyan")
        table.add_column("Key", style="green")
        table.add_column("Value", style="yellow")

        if scope:
            # 列出指定 scope
            configs = integration.bus.get_scope(scope)
            for key, value in configs.items():
                table.add_row(scope, key, str(value))
        else:
            # 列出所有 scopes
            for scope_name in integration.bus._store.keys():
                configs = integration.bus.get_scope(scope_name)
                for key, value in configs.items():
                    table.add_row(scope_name, key, str(value))

        console.print(table)

    asyncio.run(_list())


# ======================================================================
# 授权管理子命令
# ======================================================================

auth_app = typer.Typer(help="授权管理")
app.add_typer(auth_app, name="auth")


@auth_app.command("grant")
def auth_grant(
    user_id: str = typer.Argument(..., help="用户ID"),
    tool_name: str = typer.Argument(..., help="工具名称"),
    expires: Optional[int] = typer.Option(None, "--expires", "-e", help="过期时间（秒）"),
):
    """授权用户使用工具"""
    async def _grant():
        integration = await init_integration()
        await integration.grant_auth(user_id, tool_name, allowed=True, expires_in=expires)
        if expires:
            console.print(f"[green]✓ 已授权: {user_id} -> {tool_name}（{expires}秒后过期）[/green]")
        else:
            console.print(f"[green]✓ 已授权: {user_id} -> {tool_name}（永久）[/green]")

    asyncio.run(_grant())


@auth_app.command("deny")
def auth_deny(
    user_id: str = typer.Argument(..., help="用户ID"),
    tool_name: str = typer.Argument(..., help="工具名称"),
):
    """拒绝用户使用工具"""
    async def _deny():
        integration = await init_integration()
        await integration.grant_auth(user_id, tool_name, allowed=False)
        console.print(f"[red]✓ 已拒绝: {user_id} -> {tool_name}[/red]")

    asyncio.run(_deny())


@auth_app.command("revoke")
def auth_revoke(
    user_id: str = typer.Argument(..., help="用户ID"),
    tool_name: str = typer.Argument(..., help="工具名称"),
):
    """撤销用户授权"""
    async def _revoke():
        integration = await init_integration()
        await integration.auth.revoke(user_id, tool_name)
        console.print(f"[yellow]✓ 已撤销: {user_id} -> {tool_name}[/yellow]")

    asyncio.run(_revoke())


@auth_app.command("check")
def auth_check(
    user_id: str = typer.Argument(..., help="用户ID"),
    tool_name: str = typer.Argument(..., help="工具名称"),
):
    """检查用户授权状态"""
    async def _check():
        integration = await init_integration()
        allowed, reason = await integration.check_auth(user_id, tool_name)
        if allowed:
            console.print(f"[green]✓ {user_id} 可以使用 {tool_name}: {reason}[/green]")
        else:
            console.print(f"[red]✗ {user_id} 不能使用 {tool_name}: {reason}[/red]")

    asyncio.run(_check())


@auth_app.command("list")
def auth_list(
    user_id: str = typer.Argument(..., help="用户ID"),
):
    """列出用户的所有授权"""
    async def _list():
        integration = await init_integration()
        auths = await integration.auth.list_user_auth(user_id)

        if not auths:
            console.print(f"[yellow]{user_id} 没有授权记录[/yellow]")
            return

        table = Table(title=f"用户 {user_id} 的授权列表")
        table.add_column("Tool", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Granted At", style="yellow")
        table.add_column("Expires", style="red")

        for tool_name, auth in auths.items():
            status = "✓ 允许" if auth.allowed else "✗ 拒绝"
            expires = "从不" if auth.expires_at is None else f"{auth.expires_at:.0f}"
            table.add_row(
                tool_name,
                status,
                f"{auth.granted_at:.0f}",
                expires,
            )

        console.print(table)

    asyncio.run(_list())


# ======================================================================
# 演示命令
# ======================================================================

@app.command("demo")
def config_demo():
    """运行实时配置系统演示"""
    console.print("[bold]MindBot 实时配置系统演示[/bold]\n")

    async def _demo():
        integration = await init_integration()

        # 演示 1: 基本配置
        console.print("[cyan]1. 基本配置读写[/cyan]")
        await integration.set("global", "temperature", "0.8")
        value = await integration.get("global", "temperature")
        console.print(f"   设置: temperature = 0.8")
        console.print(f"   读取: temperature = {value}")

        # 演示 2: 授权管理
        console.print("\n[cyan]2. 授权管理[/cyan]")
        await integration.grant_auth("demo_user", "delete_file", allowed=True, expires_in=3600)
        allowed, reason = await integration.check_auth("demo_user", "delete_file")
        console.print(f"   授权: demo_user -> delete_file (1小时过期)")
        console.print(f"   检查: {'✓ 允许' if allowed else '✗ 拒绝'} - {reason}")

        # 演示 3: 版本信息
        console.print("\n[cyan]3. 版本信息[/cyan]")
        console.print(f"   配置版本: {integration.version}")
        console.print(f"   持久化路径: {integration._persistence.path if integration._persistence else 'N/A'}")

        console.print("\n[green]演示完成！[/green]")
        console.print("\n可用命令:")
        console.print("  mindbot config get global temperature")
        console.print("  mindbot config set global temperature 1.0")
        console.print("  mindbot config auth grant user_123 delete_file --expires 3600")
        console.print("  mindbot config auth check user_123 delete_file")

    asyncio.run(_demo())


# ======================================================================
# Shell 集成
# ======================================================================

def handle_config_command(args: list[str]) -> bool:
    """处理配置命令（用于 shell 模式）

    返回 True 表示命令已处理，False 表示未知命令
    """
    if not args:
        return False

    cmd = args[0].lower()

    if cmd == "config":
        if len(args) == 1:
            # 显示帮助
            console.print("[bold]配置命令:[/bold]")
            console.print("  config get <scope> <key>      获取配置")
            console.print("  config set <scope> <key> <val> 设置配置")
            console.print("  config list [scope]           列出配置")
            console.print("  config auth grant <user> <tool> [--expires <sec>]  授权")
            console.print("  config auth revoke <user> <tool> 撤销授权")
            console.print("  config auth check <user> <tool>  检查授权")
            console.print("  config auth list <user>       列出用户授权")
            console.print("  config demo                   运行演示")
            return True

        # 处理子命令
        sub_args = args[1:]
        if len(sub_args) >= 1:
            sub_cmd = sub_args[0]
            if sub_cmd == "get" and len(sub_args) >= 3:
                config_get(sub_args[1], sub_args[2])
            elif sub_cmd == "set" and len(sub_args) >= 4:
                config_set(sub_args[1], sub_args[2], sub_args[3])
            elif sub_cmd == "list":
                config_list(sub_args[1] if len(sub_args) > 1 else None)
            elif sub_cmd == "demo":
                config_demo()
            elif sub_cmd == "auth":
                if len(sub_args) >= 2:
                    auth_cmd = sub_args[1]
                    # auth 命令处理
                    if auth_cmd == "grant" and len(sub_args) >= 4:
                        # 解析 --expires 选项
                        expires = None
                        if "--expires" in sub_args:
                            idx = sub_args.index("--expires")
                            if idx + 1 < len(sub_args):
                                expires = int(sub_args[idx + 1])
                        auth_grant(sub_args[2], sub_args[3], expires)
                    elif auth_cmd == "revoke" and len(sub_args) >= 4:
                        auth_revoke(sub_args[2], sub_args[3])
                    elif auth_cmd == "check" and len(sub_args) >= 4:
                        auth_check(sub_args[2], sub_args[3])
                    elif auth_cmd == "list" and len(sub_args) >= 3:
                        auth_list(sub_args[2])
                    else:
                        console.print(f"[yellow]未知 auth 命令: {auth_cmd}[/yellow]")
                else:
                    console.print("[yellow]用法: config auth <grant|revoke|check|list> ...[/yellow]")
            else:
                console.print(f"[yellow]未知 config 命令: {sub_cmd}[/yellow]")
        return True

    return False


if __name__ == "__main__":
    app()
