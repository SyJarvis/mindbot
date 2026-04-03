"""MindBot CLI."""

from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

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


def _copy_builtin_skills(skills_dir: Path) -> None:
    """Copy built-in skills from templates to *skills_dir*, skipping existing ones."""
    from importlib import resources

    templates = resources.files("mindbot.templates").joinpath("skills")
    for skill_entry in templates.iterdir():
        if not skill_entry.is_dir():
            continue
        target = skills_dir / skill_entry.name
        if target.exists():
            continue
        # Recursively copy the skill directory
        _copy_tree(skill_entry, target)


def _copy_tree(src, dst: Path) -> None:
    """Recursively copy a directory tree from an importlib resource path."""
    from importlib import resources
    import shutil

    dst.mkdir(parents=True, exist_ok=True)
    for entry in src.iterdir():
        child = dst / entry.name
        if entry.is_dir():
            _copy_tree(entry, child)
        else:
            child.write_bytes(entry.read_bytes())


def _find_config_file() -> Path | None:
    """Find the active config file (JSON only)."""
    root = Path.home() / ".mindbot"
    json_file = root / "settings.json"
    if json_file.exists():
        return json_file
    return None


# ======================================================================
# generate-config / onboard
# ======================================================================

@app.command("generate-config")
@app.command("onboard")  # Keep onboard for backward compatibility
def onboard(
    skip_ollama: bool = typer.Option(
        False, "--skip-ollama", help="Skip Ollama installation check"
    ),
):
    """Generate default configuration file and initialize workspace."""
    root = Path.home() / ".mindbot"
    root.mkdir(parents=True, exist_ok=True)

    config_file = root / "settings.json"
    system_file = root / "SYSTEM.md"

    if config_file.exists() or system_file.exists():
        existing = [f.name for f in (config_file, system_file) if f.exists()]
        console.print(f"[yellow]Files already exist: {', '.join(existing)}[/yellow]")
        if not typer.confirm("Overwrite all?"):
            return

    config_file.write_text(_read_template("settings.example.json"), encoding="utf-8")
    console.print(f"[green]✓[/green] Created {config_file}")

    system_file.write_text(_read_template("SYSTEM.md"), encoding="utf-8")
    console.print(f"[green]✓[/green] Created {system_file}")

    # Create workspace sub-directories
    for d in ("skills", "memory", "history", "cron"):
        (root / d).mkdir(exist_ok=True)

    # Copy built-in skills from templates (skip if user skill already exists)
    _copy_builtin_skills(root / "skills")

    console.print(f"[green]✓[/green] Initialized workspace at {root}")

    # Ollama setup
    if not skip_ollama:
        console.print("\n[bold]Checking Ollama setup...[/bold]")
        try:
            from mindbot.utils.ollama_setup import OllamaSetup

            def progress(msg: str) -> None:
                console.print(f"  [dim]{msg}[/dim]")

            setup = OllamaSetup(progress_callback=progress)

            if setup.is_installed():
                console.print("[green]✓[/green] Ollama is installed")
                if setup.is_running():
                    console.print("[green]✓[/green] Ollama service is running")
                else:
                    console.print("[yellow]⚠[/yellow] Ollama service is not running, starting...")
                    if setup.start_service():
                        console.print("[green]✓[/green] Ollama service started")
                    else:
                        console.print("[red]✗[/red] Failed to start Ollama service")
                        console.print("[yellow]Please start Ollama manually: ollama serve[/yellow]")

                if setup.is_model_downloaded("qwen3.5:2b"):
                    console.print("[green]✓[/green] Model qwen3.5:2b is ready")
                else:
                    console.print("[yellow]⚠[/yellow] Model qwen3.5:2b not found, downloading...")
                    if setup.pull_model("qwen3.5:2b"):
                        console.print("[green]✓[/green] Model qwen3.5:2b downloaded")
                    else:
                        console.print("[red]✗[/red] Failed to download model")
                        console.print("[yellow]You can download it manually: ollama pull qwen3.5:2b[/yellow]")
            else:
                console.print("[yellow]⚠[/yellow] Ollama not found")
                if typer.confirm("Install Ollama now?"):
                    if setup.install():
                        if setup.start_service() and setup.pull_model("qwen3.5:2b"):
                            console.print("[green]✓[/green] Ollama setup complete")
                        else:
                            console.print("[yellow]Please complete Ollama setup manually[/yellow]")
                    else:
                        console.print("[yellow]Please install Ollama manually from https://ollama.com[/yellow]")
                else:
                    console.print("[yellow]Skipped Ollama installation[/yellow]")
                    console.print("[dim]You can install it later from https://ollama.com[/dim]")
        except Exception as e:
            console.print(f"[yellow]⚠ Ollama check failed: {e}[/yellow]")

    console.print("\n[bold]Next steps:[/bold]")
    console.print("  1. Edit [cyan]~/.mindbot/settings.json[/cyan] to configure providers")
    console.print("  2. Edit [cyan]~/.mindbot/SYSTEM.md[/cyan] to customise the system prompt")
    console.print("  3. Run  [cyan]mindbot serve[/cyan]")


# ======================================================================
# chat
# ======================================================================

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


# ======================================================================
# status
# ======================================================================

@app.command()
def status():
    """Show mindbot status."""
    config_file = _find_config_file()

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


# ======================================================================
# Slash command handler
# ======================================================================

def _handle_slash_command(cmd: str, bot: Any) -> None:
    """Dispatch slash commands in the interactive shell.

    Supported commands:
        /model                List available models (highlight current)
        /model <instance/model>   Switch to a different model
        /help                 Show available slash commands
        /status               Show bot status
    """
    parts = cmd.split(maxsplit=1)
    command = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if command == "/model":
        _cmd_model(bot, arg)
    elif command == "/help":
        _cmd_help()
    elif command == "/status":
        _cmd_status(bot)
    else:
        console.print(f"[yellow]Unknown command: {command}[/yellow]")
        console.print("[dim]Type /help for available commands[/dim]")


def _cmd_model(bot: Any, arg: str) -> None:
    """Handle /model command."""
    available = bot.list_available_models()
    current = bot.model

    if not arg:
        # List models
        console.print("[bold]Available models:[/bold]")
        for m in available:
            if m == current:
                console.print(f"  [green]● {m}[/green] [dim](current)[/dim]")
            else:
                console.print(f"  [dim]○ {m}[/dim]")
        console.print(f"\n[dim]Use /model <instance/model> to switch[/dim]")
        return

    # Switch model
    model_ref = arg
    if model_ref not in available:
        # Try partial match
        matches = [m for m in available if m.endswith("/" + model_ref) or model_ref in m]
        if len(matches) == 1:
            model_ref = matches[0]
        elif len(matches) > 1:
            console.print(f"[yellow]Ambiguous match. Did you mean?[/yellow]")
            for m in matches:
                console.print(f"  {m}")
            return
        else:
            console.print(f"[red]Model not found: {arg}[/red]")
            console.print(f"[dim]Available: {', '.join(available)}[/dim]")
            return

    try:
        bot.set_model(model_ref)
        console.print(f"[green]✓ Switched to {model_ref}[/green]")
    except Exception as e:
        console.print(f"[red]Failed to switch model: {e}[/red]")


def _cmd_help() -> None:
    """Show available slash commands."""
    console.print("[bold]Slash commands:[/bold]")
    console.print("  /model              List available models")
    console.print("  /model <name>       Switch model (e.g. /model my-ollama/qwen3)")
    console.print("  /status             Show current bot status")
    console.print("  /help               Show this help")
    console.print("  exit, quit, bye     Exit the shell")


def _cmd_status(bot: Any) -> None:
    """Show bot status."""
    console.print(f"  Model:    [cyan]{bot.model}[/cyan]")
    console.print(f"  Provider: [cyan]{bot.provider}[/cyan]")


# ======================================================================
# shell
# ======================================================================

@app.command()
def shell(
    session_id: str = typer.Option("default", "--session", "-s", help="Session ID"),
):
    """Start interactive shell mode."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.styles import Style
    from rich.markdown import Markdown

    config_file = _find_config_file()
    if not config_file:
        console.print("[red]Error: Config not found. Run 'mindbot generate-config' first.[/red]")
        raise typer.Exit(1)

    root = Path.home() / ".mindbot"
    history_dir = root / "history" / "cli_history"
    history_dir.parent.mkdir(parents=True, exist_ok=True)

    style = Style.from_dict({"prompt": "ansicyan bold"})
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
    console.print(f"[dim]Session: {session_id} | Model: {bot.model}[/dim]")
    console.print("[dim]Type /help for slash commands[/dim]\n")

    while True:
        try:
            user_input = session.prompt()
            if not user_input.strip():
                continue
            if user_input.strip().lower() in ["exit", "quit", "bye"]:
                console.print("[yellow]Goodbye![/yellow]")
                break

            # ---- Slash command handling ----
            stripped = user_input.strip()
            if stripped.startswith("/"):
                _handle_slash_command(stripped, bot)
                continue

            console.print("[dim]Thinking...[/dim]")
            import asyncio
            agent_response = asyncio.run(bot.chat(user_input, session_id=session_id))
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


# ======================================================================
# serve
# ======================================================================

@app.command()
def serve(
    port: int = typer.Option(31211, "--port", "-p", help="Port to listen on"),
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Host to bind to"),
):
    """Start MindBot server with all enabled channels."""
    import asyncio

    config_file = _find_config_file()
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


# ======================================================================
# config subcommand group
# ======================================================================

config_app = typer.Typer(help="Manage configuration")


@config_app.command("show")
def config_show():
    """Show current configuration."""
    config_file = _find_config_file()
    if not config_file:
        console.print("[yellow]Config not found. Run 'mindbot generate-config' first.[/yellow]")
        raise typer.Exit(1)

    try:
        text = config_file.read_text(encoding="utf-8")
        syntax = Syntax(text, "json")
        panel = Panel(syntax, title=f"Configuration: {config_file}", border_style="green")
        console.print(panel)
    except Exception as e:
        console.print(f"[red]Error reading config: {e}[/red]")
        raise typer.Exit(1)


@config_app.command("validate")
def config_validate():
    """Validate the current configuration."""
    config_file = _find_config_file()
    if not config_file:
        console.print("[yellow]Config not found. Run 'mindbot generate-config' first.[/yellow]")
        raise typer.Exit(1)

    try:
        from mindbot.config.loader import load_config
        config = load_config(config_file)

        console.print(f"[green]✓[/green] Config is valid: {config_file}")
        console.print(f"  Agent model: {config.agent.model}")
        console.print(f"  Providers: {', '.join(config.providers.keys()) or '(none)'}")
        console.print(f"  Routing: {'auto' if config.routing.auto else 'manual'}")
        console.print(f"  Memory: {config.memory.storage_path}")

        # Validate provider types
        from mindbot.config.schema import KNOWN_PROVIDER_TYPES
        for name, prov in config.providers.items():
            if prov.type not in KNOWN_PROVIDER_TYPES:
                console.print(
                    f"  [yellow]⚠[/yellow] Provider '{name}' has unknown type '{prov.type}'. "
                    f"Known types: {', '.join(KNOWN_PROVIDER_TYPES)}"
                )
            else:
                ep_count = len(prov.get_effective_endpoints())
                model_count = sum(len(ep.models) for ep in prov.get_effective_endpoints())
                console.print(f"  [green]✓[/green] {name} (type={prov.type}, endpoints={ep_count}, models={model_count})")

    except Exception as e:
        console.print(f"[red]✗ Config validation failed: {e}[/red]")
        raise typer.Exit(1)


# Register config subcommand
app.add_typer(config_app, name="config")


if __name__ == "__main__":
    app()
