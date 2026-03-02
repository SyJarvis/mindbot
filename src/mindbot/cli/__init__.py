"""MindBot CLI."""

import typer
from rich.console import Console

from mindbot import __version__, __logo__

app = typer.Typer(
    name="mindbot",
    help=f"{__logo__}\nMindBot - AI Assistant",
    no_args_is_help=False,
)

console = Console()


def version_callback(value: bool):
    if value:
        console.print(f"MindBot v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(None, "--version", "-v", callback=version_callback, is_eager=True),
):
    """MindBot CLI."""
    pass


def _read_template(name: str) -> str:
    """Read a bundled template file from the ``mindbot.templates`` package."""
    from importlib import resources

    ref = resources.files("mindbot.templates").joinpath(name)
    return ref.read_text(encoding="utf-8")


@app.command("generate-config")
@app.command("onboard")  # Keep onboard for backward compatibility
def onboard():
    """Generate default configuration file and initialize workspace."""
    from pathlib import Path

    root = Path.home() / ".mindbot"
    root.mkdir(parents=True, exist_ok=True)

    config_file = root / "settings.yaml"
    system_file = root / "SYSTEM.md"

    if config_file.exists() or system_file.exists():
        existing = [f.name for f in (config_file, system_file) if f.exists()]
        console.print(f"[yellow]Files already exist: {', '.join(existing)}[/yellow]")
        if not typer.confirm("Overwrite all?"):
            return

    config_file.write_text(_read_template("settings.example.yaml"), encoding="utf-8")
    console.print(f"[green]✓[/green] Created {config_file}")

    system_file.write_text(_read_template("SYSTEM.md"), encoding="utf-8")
    console.print(f"[green]✓[/green] Created {system_file}")

    # Create workspace sub-directories
    for d in ("skills", "memory", "history"):
        (root / d).mkdir(exist_ok=True)

    console.print(f"[green]✓[/green] Initialized workspace at {root}")
    console.print("\n[bold]Next steps:[/bold]")
    console.print("  1. Edit [cyan]~/.mindbot/settings.yaml[/cyan] to configure providers")
    console.print("  2. Edit [cyan]~/.mindbot/SYSTEM.md[/cyan] to customise the system prompt")
    console.print("  3. Run  [cyan]mindbot serve[/cyan]")


@app.command()
def chat(
    message: str = typer.Option(None, "--message", "-m", help="Message to send"),
    session_id: str = typer.Option("default", "--session", "-s", help="Session ID"),
):
    """Send a single message to the bot."""
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


@app.command()
def status():
    """Show mindbot status."""
    from pathlib import Path

    root = Path.home() / ".mindbot"
    config_file = root / "settings.yaml"

    console.print(__logo__)
    console.print(f"\n[bold]Status:[/bold]")
    console.print(f"  Config: {config_file} {'[green]✓[/green]' if config_file.exists() else '[red]✗[/red]'}")

    if config_file.exists():
        try:
            from mindbot import MindBot

            bot = MindBot()
            console.print(f"  Model: {bot.model}")
            console.print(f"  Provider: {bot.provider}")
        except Exception as e:
            console.print(f"  [yellow]Bot not ready: {e}[/yellow]")


@app.command()
def shell(
    session_id: str = typer.Option("default", "--session", "-s", help="Session ID"),
):
    """Start interactive shell mode."""
    from pathlib import Path
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.styles import Style
    from rich.markdown import Markdown
    import shutil

    root = Path.home() / ".mindbot"
    config_file = root / "settings.yaml"

    if not config_file.exists():
        console.print("[red]Error: Config not found. Run 'mindbot generate-config' first.[/red]")
        raise typer.Exit(1)

    # 设置历史记录
    history_dir = root / "history" / "cli_history"
    history_dir.parent.mkdir(parents=True, exist_ok=True)

    # 创建 prompt session
    style = Style.from_dict({
        "prompt": "ansicyan bold",
    })

    session = PromptSession(
        history=FileHistory(str(history_dir)),
        style=style,
    )

    try:
        from mindbot import MindBot

        bot = MindBot()
    except Exception as e:
        console.print(f"[red]Error initializing bot: {e}[/red]")
        raise typer.Exit(1)

    console.print("[bold green]MindBot Shell[/bold green] (Ctrl+C to exit)")
    console.print(f"[dim]Session: {session_id}[/dim]\n")

    while True:
        try:
            user_input = session.prompt()

            if not user_input.strip():
                continue

            if user_input.strip().lower() in ["exit", "quit", "bye"]:
                console.print("[yellow]Goodbye![/yellow]")
                break

            console.print("[dim]Thinking...[/dim]")

            import asyncio
            agent_response = asyncio.run(bot.chat(user_input, session_id=session_id))

            # 使用 Rich 渲染 Markdown
            md = Markdown(agent_response.content)
            console.print(md)
            console.print()

        except KeyboardInterrupt:
            console.print("\n[yellow]Use 'exit' or Ctrl+D to quit[/yellow]")
        except EOFError:
            console.print("\n[yellow]Goodbye![/yellow]")
            break
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")


# Config subcommand group
config_app = typer.Typer(help="Manage configuration")


@config_app.command("show")
def config_show():
    """Show current configuration."""
    from pathlib import Path
    import yaml

    config_file = Path.home() / ".mindbot" / "settings.yaml"

    if not config_file.exists():
        console.print("[yellow]Config not found. Run 'mindbot generate-config' first.[/yellow]")
        raise typer.Exit(1)

    try:
        with open(config_file) as f:
            config_data = yaml.safe_load(f)

        # 使用 Rich 格式化输出
        from rich.syntax import Syntax
        from rich.panel import Panel

        syntax = Syntax(yaml.dump(config_data, default_flow_style=False, allow_unicode=True), "yaml")
        panel = Panel(syntax, title=f"Configuration: {config_file}", border_style="green")
        console.print(panel)

    except Exception as e:
        console.print(f"[red]Error reading config: {e}[/red]")
        raise typer.Exit(1)


# Register config subcommand
app.add_typer(config_app, name="config")


@app.command()
def serve(
    port: int = typer.Option(31211, "--port", "-p", help="Port to listen on"),
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Host to bind to"),
):
    """Start MindBot server with all enabled channels."""
    import asyncio
    from pathlib import Path

    root = Path.home() / ".mindbot"
    config_file = root / "settings.yaml"

    if not config_file.exists():
        console.print("[red]Error: Config not found. Run 'mindbot generate-config' first.[/red]")
        raise typer.Exit(1)

    async def main():
        from mindbot import Config, MessageBus, ChannelManager
        from mindbot.bus import InboundMessage, OutboundMessage
        from mindbot.bot import MindBot
        from mindbot.config.loader import load_config

        # Load config
        config = load_config(config_file)

        # Create message bus
        bus = MessageBus()

        # Create channel manager
        channel_manager = ChannelManager(config, bus)

        # Create agent task
        async def run_agent():
            bot = MindBot()

            while True:
                try:
                    msg = await asyncio.wait_for(bus.consume_inbound(), timeout=1.0)

                    # Get session_id from metadata
                    session_id = msg.metadata.get("session_id", "default")

                    # Process message through the unified async entry point
                    agent_response = await bot.chat(msg.content, session_id=session_id)

                    # Send response back
                    reply = OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content=agent_response.content,
                    )
                    await bus.publish_outbound(reply)

                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    console.print(f"[red]Agent error: {e}[/red]")

        # Start everything
        console.print(f"[bold green]Starting MindBot server on {host}:{port}[/bold green]")

        # Start channels
        channel_task = asyncio.create_task(channel_manager.start_all())

        # Start agent
        agent_task = asyncio.create_task(run_agent())

        try:
            await asyncio.gather(channel_task, agent_task)
        except KeyboardInterrupt:
            console.print("\n[yellow]Shutting down...[/yellow]")
            await channel_manager.stop_all()
            agent_task.cancel()

    asyncio.run(main())


if __name__ == "__main__":
    app()
