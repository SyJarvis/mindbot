"""serve 命令。"""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console

from mindbot.cli._shared import console, find_config_file


def serve(
    port: int = typer.Option(31211, "--port", "-p", help="Port to listen on"),
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Host to bind to"),
) -> None:
    """启动 MindBot 服务器及所有已启用的 channel。"""

    config_file = find_config_file()
    if not config_file:
        console.print("[red]Error: Config not found. Run 'mindbot generate-config' first.[/red]")
        raise typer.Exit(1)

    async def main():
        from mindbot import MessageBus, ChannelManager
        from mindbot.bot import MindBot
        from mindbot.bus.events import OutboundMessage
        from mindbot.config.loader import load_config
        from mindbot.config.store import ConfigStore

        config = load_config(config_file)
        store = ConfigStore(config, path=config_file)

        bus = MessageBus()
        channel_manager = ChannelManager(config, bus)
        bot = MindBot(config_store=store)

        # Wire cron delivery: agent response → bus → channel
        async def _deliver(channel: str, to: str, content: str) -> None:
            await bus.publish_outbound(OutboundMessage(
                channel=channel,
                chat_id=to,
                content=content,
            ))

        bot.set_delivery_callback(_deliver)

        # Set channel context on bot before each inbound message,
        # so tools (e.g. cron_add) can auto-fill delivery info.
        channel_manager.set_inbound_context_callback(
            lambda msg: setattr(bot, "_channel_ctx", {"channel": msg.channel, "to": msg.chat_id}),
        )

        channel_manager.set_chat_handler(
            lambda message, session_id: bot.chat(message, session_id=session_id),
        )

        http_channel = channel_manager.get_channel("http")
        if http_channel is not None and hasattr(http_channel, "set_chat_handlers"):
            http_channel.set_chat_handlers(
                stream_handler=lambda message, session_id: bot.chat_stream(message, session_id=session_id),
            )

        console.print(f"[bold green]Starting MindBot server on {host}:{port}[/bold green]")

        await bot.cron.start()
        channel_task = asyncio.create_task(channel_manager.start_all())

        try:
            await channel_task
        except KeyboardInterrupt:
            console.print("\n[yellow]Shutting down...[/yellow]")
            await bot.cron.stop()
            await channel_manager.stop_all()

    asyncio.run(main())
