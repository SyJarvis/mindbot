"""chat 命令。"""

from __future__ import annotations

import typer
from rich.console import Console

from mindbot.cli._shared import console


def chat(
    message: str = typer.Option(None, "--message", "-m", help="Message to send"),
    session_id: str = typer.Option("default", "--session", "-s", help="Session ID"),
) -> None:
    """发送单条消息给 bot。"""
    if not message:
        console.print("[red]Error: --message is required[/red]")
        raise typer.Exit(1)

    try:
        import asyncio
        from mindbot import MindBot

        async def _run() -> str:
            bot = MindBot()
            response = await bot.chat(message, session_id=session_id)
            return response.content

        console.print(asyncio.run(_run()))
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
