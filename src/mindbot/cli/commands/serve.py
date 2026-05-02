"""serve 命令。"""

from __future__ import annotations

import typer
from rich.console import Console

from mindbot.cli._shared import console, find_config_file


def serve(
    port: int = typer.Option(31211, "--port", "-p", help="Port to listen on"),
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Host to bind to"),
) -> None:
    """启动 MindBot 服务器及所有已启用的 channel。"""
    import asyncio

    config_file = find_config_file()
    if not config_file:
        console.print("[red]Error: Config not found. Run 'mindbot generate-config' first.[/red]")
        raise typer.Exit(1)

    async def main():
        from mindbot import MessageBus, ChannelManager
        from mindbot.bot import MindBot
        from mindbot.config.loader import load_config
        from mindbot.config.store import ConfigStore

        config = load_config(config_file)
        store = ConfigStore(config, path=config_file)

        bus = MessageBus()
        channel_manager = ChannelManager(config, bus)
        bot = MindBot(config_store=store)
        channel_manager.set_chat_handler(
            lambda message, session_id: bot.chat(message, session_id=session_id),
        )

        http_channel = channel_manager.get_channel("http")
        if http_channel is not None and hasattr(http_channel, "set_chat_handlers"):
            http_channel.set_chat_handlers(
                stream_handler=lambda message, session_id: bot.chat_stream(message, session_id=session_id),
            )

        console.print(f"[bold green]Starting MindBot server on {host}:{port}[/bold green]")

        channel_task = asyncio.create_task(channel_manager.start_all())

        try:
            await channel_task
        except KeyboardInterrupt:
            console.print("\n[yellow]Shutting down...[/yellow]")
            await channel_manager.stop_all()

    asyncio.run(main())
