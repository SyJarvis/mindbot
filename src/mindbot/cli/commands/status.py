"""status 命令。"""

from __future__ import annotations

import typer
from rich.console import Console

from mindbot import __logo__
from mindbot.cli._shared import console, find_config_file


def status() -> None:
    """显示 mindbot 状态。"""
    config_file = find_config_file()

    console.print(__logo__)
    console.print(f"\n[bold]Status:[/bold]")
    if config_file:
        console.print(f"  Config: {config_file} [green]✓[/green]")
    else:
        console.print(f"  Config: [red]✗ not found[/red]")

    if config_file and config_file.exists():
        try:
            from mindbot import MindBot
            bot = MindBot()
            console.print(f"  Model: {bot.model}")
            console.print(f"  Provider: {bot.provider}")
        except Exception as e:
            console.print(f"  [yellow]Bot not ready: {e}[/yellow]")
