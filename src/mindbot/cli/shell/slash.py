"""Shell slash 命令注册与分发。"""

from __future__ import annotations

from typing import Any

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()


async def handle_slash_command(cmd: str, bot: Any, shell_ctx: Any = None) -> None:
    """分发交互式 shell 中的 slash 命令。

    支持的命令：
        /model                交互式切换模型
        /model <instance/model>   切换到不同模型
        /skill                列出可用的 skills
        /skill <name>         显示 skill 详情或触发 skill
        /help (h, ?)          显示帮助
        /status               显示 bot 状态
        /config               实时配置命令
        /theme                切换主题
    """
    parts = cmd.split()
    command = parts[0].lower()
    args = parts[1:] if len(parts) > 1 else []

    if command in ("/model", "/m"):
        arg = " ".join(args)
        await cmd_model(bot, arg)
    elif command == "/skill":
        await cmd_skill(bot, args)
    elif command in ("/help", "/h", "/?"):
        cmd_help()
    elif command == "/status":
        cmd_status(bot, shell_ctx)
    elif command == "/config":
        cmd_config(args)
    elif command == "/theme":
        cmd_theme(args)
    elif command == "/clear":
        cmd_clear(bot)
    elif command == "/compact":
        await cmd_compact(bot)
    else:
        console.print(f"[yellow]Unknown command: {command}[/yellow]")
        console.print("[dim]Type /help for available commands[/dim]")


# ---------------------------------------------------------------------------
# /model — 交互式模型切换
# ---------------------------------------------------------------------------

async def cmd_model(bot: Any, arg: str) -> None:
    """处理 /model 命令。无参数时交互式选择，有参数时直接切换。"""
    available = bot.list_available_models()
    current = bot.model

    if not available:
        console.print("[yellow]No models available.[/yellow]")
        return

    if not arg:
        # 交互式选择
        from prompt_toolkit.shortcuts.choice_input import ChoiceInput

        choices: list[tuple[str, str]] = []
        for m in available:
            marker = " (current)" if m == current else ""
            provider = m.rsplit("/", 1)[0] if "/" in m else "local"
            label = f"{m} ({provider}){marker}"
            choices.append((m, label))

        default = current if current in [c[0] for c in choices] else choices[0][0]

        try:
            selected = await ChoiceInput(
                message="Select a model (\u2191\u2193 navigate, Enter select, Ctrl+C cancel):",
                options=choices,
                default=default,
            ).prompt_async()
        except (EOFError, KeyboardInterrupt):
            return

        if not selected or selected == current:
            return
        arg = selected

    # 切换模型
    model_ref = arg
    if model_ref not in available:
        # 尝试部分匹配
        matches = [m for m in available if m.endswith("/" + model_ref) or model_ref in m]
        if len(matches) == 1:
            model_ref = matches[0]
        elif len(matches) > 1:
            console.print("[yellow]Ambiguous match. Did you mean?[/yellow]")
            for m in matches:
                console.print(f"  {m}")
            return
        else:
            console.print(f"[red]Model not found: {arg}[/red]")
            console.print(f"[dim]Available: {', '.join(available)}[/dim]")
            return

    try:
        bot.set_model(model_ref)
        console.print(f"[green]\u2713 Switched to {model_ref}[/green]")
    except Exception as e:
        console.print(f"[red]Failed to switch model: {e}[/red]")


# ---------------------------------------------------------------------------
# /help — Rich 格式化帮助
# ---------------------------------------------------------------------------

_KEYBOARD_SHORTCUTS = [
    ("Alt-Enter / Ctrl-J", "Insert newline"),
    ("Ctrl-O", "Edit in external editor ($VISUAL/$EDITOR)"),
    ("Ctrl-V", "Paste from clipboard"),
    ("Ctrl-C", "Interrupt / exit"),
]

_SLASH_COMMANDS = [
    ("/model", "List or switch models (interactive)"),
    ("/skill", "List or invoke skills"),
    ("/help", "Show this help"),
    ("/status", "Show bot status"),
    ("/config", "Real-time config commands"),
    ("/theme", "Switch theme (dark/light)"),
    ("/clear", "Clear all conversation context"),
    ("/compact", "Force compress conversation context"),
    ("exit / quit / bye", "Exit the shell"),
]


def cmd_help() -> None:
    """显示 kimi-cli 风格的 Rich 帮助。"""
    renderables: list[Any] = []

    # MindBot brand quote
    renderables.append(
        Group(
            Text.from_markup("[dim]The mind is everything. What you think you become.[/dim]"),
            Text.from_markup("[dim italic]\u2014 adapted for MindBot[/dim italic]"),
        )
    )
    renderables.append(Text(""))
    renderables.append(
        Text("MindBot is ready to help! Send messages and get things done.")
    )
    renderables.append(Text(""))

    # Keyboard shortcuts (yellow)
    renderables.append(Text.from_markup("[bold]Keyboard shortcuts:[/bold]"))
    for name, desc in _KEYBOARD_SHORTCUTS:
        renderables.append(
            Text.from_markup(f"  [yellow]{name}[/yellow]: [dim]{desc}[/dim]")
        )
    renderables.append(Text(""))

    # Slash commands (cyan)
    renderables.append(Text.from_markup("[bold]Slash commands:[/bold]"))
    for name, desc in _SLASH_COMMANDS:
        renderables.append(
            Text.from_markup(f"  [cyan]{name}[/cyan]: [dim]{desc}[/dim]")
        )

    with console.pager(styles=True):
        console.print(Group(*renderables))


# ---------------------------------------------------------------------------
# /status — Rich Panel + Table
# ---------------------------------------------------------------------------

def cmd_status(bot: Any, shell_ctx: Any = None) -> None:
    """显示 bot 状态（Rich Panel 格式）。"""
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold cyan", width=12)
    table.add_column()

    table.add_row("Model:", bot.model)
    table.add_row("Provider:", bot.provider)

    # Health status
    if getattr(bot.config, "routing", None) and bot.config.routing.auto:
        health_status = bot.get_health_status()
        if health_status:
            table.add_row("", "")
            for key, status in health_status.items():
                is_healthy = status.get("is_healthy", True)
                symbol = "[green]OK[/green]" if is_healthy else "[red]DOWN[/red]"
                table.add_row(f"{key}:", symbol)

                if "last_probe_time" in status and status["last_probe_time"] > 0:
                    probe_success = status.get("last_probe_success")
                    if probe_success is not None:
                        latency = status.get("last_probe_latency_ms", 0)
                        probe_color = "green" if probe_success else "red"
                        probe_text = "success" if probe_success else "failed"
                        table.add_row(
                            "  probe:",
                            f"[{probe_color}]{probe_text}[/{probe_color}] ({latency:.0f}ms)",
                        )

                if not is_healthy and "failures" in status:
                    table.add_row("  failures:", f"[red]{status['failures']}[/red]")

    # Shell context
    if shell_ctx is not None:
        table.add_row("", "")
        table.add_row("Workspace:", str(shell_ctx.workspace))
        table.add_row("CWD:", str(shell_ctx.session_cwd))
        table.add_row("Root:", str(shell_ctx.effective_root))
        table.add_row("Trust:", str(shell_ctx.trust_status))
        trusted = ", ".join(str(p) for p in shell_ctx.trusted_paths) or "(none)"
        table.add_row("Trusted:", trusted)
        table.add_row(
            "Shell:",
            bot.config.agent.shell_execution.policy.value,
        )

    console.print(
        Panel(table, title="Status", border_style="cyan", padding=(1, 2))
    )


# ---------------------------------------------------------------------------
# /config
# ---------------------------------------------------------------------------

def cmd_config(args: list[str]) -> None:
    """处理 shell 中的 /config 命令。"""
    from mindbot.cli.config_cmd import handle_config_command
    handle_config_command(["config"] + args)


# ---------------------------------------------------------------------------
# /theme
# ---------------------------------------------------------------------------

def cmd_theme(args: list[str]) -> None:
    """处理 /theme 命令。"""
    if not args:
        console.print("[bold]Available themes:[/bold]")
        console.print("  [cyan]dark[/cyan]   - Dark background (default)")
        console.print("  [cyan]light[/cyan]  - Light background")
        console.print("\n[dim]Usage: /theme <name>[/dim]")
        return

    from mindbot.cli.shell.theme import set_active_theme

    name = args[0].lower()
    if name not in ("dark", "light", "auto"):
        console.print(f"[red]Unknown theme: {name}[/red]")
        return

    set_active_theme(name)
    console.print(f"[green]\u2713 Switched to {name} theme[/green]")


# ---------------------------------------------------------------------------
# /skill — Skill 管理与触发
# ---------------------------------------------------------------------------

async def cmd_skill(bot: Any, args: list[str]) -> None:
    """处理 /skill 命令。

    用法：
        /skill              列出所有可用 skills
        /skill list         列出所有可用 skills
        /skill <name>       显示 skill 详情
        /skill <name> <query>  触发 skill 并发送查询
    """
    # 获取 skill registry
    # 路径: MindBot._agent._main_agent._skill_registry
    skill_registry = None

    # 尝试从 bot._agent 获取
    agent = getattr(bot, "_agent", None)
    if agent is not None:
        main_agent = getattr(agent, "_main_agent", None)
        if main_agent is not None:
            skill_registry = getattr(main_agent, "_skill_registry", None)

    if skill_registry is None:
        console.print("[yellow]Skill registry not available.[/yellow]")
        console.print("[dim]Make sure skills are enabled in settings.json[/dim]")
        return

    # 获取所有 skills
    all_skills = skill_registry.list_all()
    if not all_skills:
        console.print("[dim]No skills loaded.[/dim]")
        return

    # 无参数或 list：显示列表
    if not args or args[0].lower() == "list":
        _render_skill_list(all_skills)
        return

    # 查找指定 skill
    skill_name = args[0].lower()
    skill = skill_registry.get(skill_name)

    if skill is None:
        # 尝试模糊匹配
        matches = [s for s in all_skills if skill_name in s.name.lower()]
        if len(matches) == 1:
            skill = matches[0]
        elif len(matches) > 1:
            console.print("[yellow]Ambiguous skill name. Did you mean:[/yellow]")
            for s in matches:
                console.print(f"  - {s.name}")
            return
        else:
            console.print(f"[red]Skill not found: {args[0]}[/red]")
            _render_skill_list(all_skills)
            return

    # 有额外参数：触发 skill
    if len(args) > 1:
        query = " ".join(args[1:])
        await _invoke_skill(bot, skill, query)
        return

    # 显示 skill 详情
    _render_skill_detail(skill)


def _render_skill_list(skills: list[Any]) -> None:
    """渲染 skill 列表。"""
    table = Table(title="Available Skills", show_header=True, header_style="bold cyan")
    table.add_column("Name", style="green", width=25)
    table.add_column("Scope", style="yellow", width=10)
    table.add_column("Description", style="dim")

    for skill in sorted(skills, key=lambda s: s.name):
        desc = skill.description or "(no description)"
        if len(desc) > 60:
            desc = desc[:57] + "..."
        scope = getattr(skill, "scope", "user")
        table.add_row(skill.name, scope, desc)

    console.print(table)
    console.print()
    console.print("[dim]Usage: /skill <name> to view details, /skill <name> <query> to invoke[/dim]")


def _render_skill_detail(skill: Any) -> None:
    """渲染单个 skill 的详情。"""
    # 基本信息
    info_table = Table(show_header=False, box=None, padding=(0, 2))
    info_table.add_column(style="bold cyan", width=12)
    info_table.add_column()

    info_table.add_row("Name:", skill.name)
    info_table.add_row("Scope:", getattr(skill, "scope", "user"))
    info_table.add_row("Description:", skill.description or "(none)")
    info_table.add_row("When to use:", getattr(skill, "when_to_use", "") or "(not specified)")

    # Scripts
    scripts = getattr(skill, "scripts", [])
    if scripts:
        script_names = ", ".join(s.name for s in scripts)
        info_table.add_row("Scripts:", script_names)

    # Allowed tools
    if skill.allowed_tools:
        info_table.add_row("Tools:", ", ".join(skill.allowed_tools))

    # Source
    if hasattr(skill, "skill_dir"):
        info_table.add_row("Location:", str(skill.skill_dir))

    console.print(
        Panel(info_table, title=f"Skill: {skill.name}", border_style="green", padding=(1, 2))
    )

    # 显示 body 预览
    if hasattr(skill, "body") and skill.body:
        body_preview = skill.body[:500]
        if len(skill.body) > 500:
            body_preview += "\n..."
        console.print()
        console.print("[bold]Instructions:[/bold]")
        console.print(f"[dim]{body_preview}[/dim]")

    console.print()
    console.print(f"[dim]Usage: /skill {skill.name} <your query>[/dim]")


async def _invoke_skill(bot: Any, skill: Any, query: str) -> None:
    """触发 skill 并发送查询。"""
    # 构建包含 skill 指令的消息
    body = getattr(skill, "body", "")
    if not body:
        console.print(f"[yellow]Skill '{skill.name}' has no instructions.[/yellow]")
        return

    # 构建完整的消息内容
    message = f"""[Skill: {skill.name}]

{body}

---

User request: {query}"""

    console.print(f"[green]Invoking skill: {skill.name}[/green]")
    console.print(f"[dim]Query: {query}[/dim]")
    console.print()

    # 发送给 bot 处理
    try:
        # 使用 bot 的 chat 方法处理
        if hasattr(bot, "chat"):
            response = await bot.chat(message)
            # 提取内容部分
            if response is not None:
                content = getattr(response, "content", None)
                if content:
                    console.print(content)
                else:
                    # 如果没有 content 属性，尝试直接打印
                    console.print(str(response))
        elif hasattr(bot, "_handle_message"):
            await bot._handle_message(message)
        else:
            console.print("[yellow]Bot does not support direct message handling.[/yellow]")
            console.print("[dim]The skill instructions have been loaded.[/dim]")
    except Exception as e:
        console.print(f"[red]Error invoking skill: {e}[/red]")


# ---------------------------------------------------------------------------
# /clear — 清空上下文
# ---------------------------------------------------------------------------

def cmd_clear(bot: Any) -> None:
    """清空当前会话的所有上下文。"""
    bot.clear_context()
    console.print("[green]✓ Context cleared[/green]")


# ---------------------------------------------------------------------------
# /compact — 手动触发压缩
# ---------------------------------------------------------------------------

async def cmd_compact(bot: Any) -> None:
    """手动触发对话上下文压缩。"""
    before = bot.get_conversation_token_count()
    after = await bot.compact_context()
    if before == 0:
        console.print("[dim]Nothing to compact (conversation is empty)[/dim]")
        return
    saved = before - after
    pct = (saved / before * 100) if before > 0 else 0
    console.print(f"[green]✓ Compacted: {before} → {after} tokens ({pct:.0f}% saved)[/green]")
