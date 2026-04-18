"""MindBot CLI."""

import json
from dataclasses import dataclass, field
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


@dataclass
class _ShellEventState:
    """Render state for one interactive shell turn."""

    saw_delta: bool = False
    line_open: bool = False


@dataclass
class _ShellSessionContext:
    """Per-session shell directory and trust state."""

    config_file: Path
    workspace: Path
    session_cwd: Path
    persisted_trusted_paths: set[Path] = field(default_factory=set)
    session_trusted_paths: set[Path] = field(default_factory=set)
    session_cwd_authorized: bool | None = None

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


def _emit_shell_event(event: Any, state: _ShellEventState) -> None:
    """Render agent events in the interactive shell."""
    event_type = getattr(getattr(event, "type", None), "value", None)
    data = getattr(event, "data", {}) or {}

    if event_type == "delta":
        chunk = data.get("content", "")
        if not chunk:
            return
        if not state.line_open:
            console.print()
            state.line_open = True
        console.print(chunk, end="")
        state.saw_delta = True
        return

    if event_type == "tool_executing":
        if state.line_open:
            console.print()
            state.line_open = False
        tool_name = data.get("tool_name", "unknown")
        console.print(f"[dim]Running tool: {tool_name}[/dim]")
        return

    if event_type == "tool_result":
        if state.line_open:
            console.print()
            state.line_open = False
        tool_name = data.get("tool_name", "unknown")
        console.print(f"[dim]Tool finished: {tool_name}[/dim]")
        return

    if event_type == "error":
        if state.line_open:
            console.print()
            state.line_open = False
        message = data.get("message", "Unknown error")
        console.print(f"[red]Error: {message}[/red]")


def _render_shell_response(content: str, state: _ShellEventState) -> None:
    """Render the final assistant response in shell mode."""
    from rich.markdown import Markdown

    if state.line_open:
        console.print()
        state.line_open = False
    if not state.saw_delta and content:
        console.print(Markdown(content))
    console.print()


def _unique_paths(paths: list[Path | str]) -> list[Path]:
    resolved: list[Path] = []
    for path in paths:
        candidate = Path(path).expanduser().resolve()
        if candidate not in resolved:
            resolved.append(candidate)
    return resolved


def _resolve_shell_session_context(bot: Any, config_file: Path, launch_cwd: Path) -> _ShellSessionContext:
    """Build shell session state from config and launch directory."""
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
    persisted_trusted_paths = set(_unique_paths(list(bot.config.agent.trusted_paths)))
    authorized = is_within_allowed_roots(session_cwd, allowed_roots)
    return _ShellSessionContext(
        config_file=config_file,
        workspace=workspace,
        session_cwd=session_cwd,
        persisted_trusted_paths=persisted_trusted_paths,
        session_cwd_authorized=authorized,
    )


def _persist_trusted_path(config_file: Path, trusted_path: Path) -> None:
    """Persist *trusted_path* into the active config file."""
    data = json.loads(config_file.read_text(encoding="utf-8"))
    agent_data = data.setdefault("agent", {})
    trusted_paths = agent_data.setdefault("trusted_paths", [])
    trusted_text = str(trusted_path)
    if trusted_text not in trusted_paths:
        trusted_paths.append(trusted_text)
        config_file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _prompt_trust_session_cwd(bot: Any, shell_ctx: _ShellSessionContext) -> None:
    """Ask whether the current shell directory should be trusted."""
    if shell_ctx.session_cwd_authorized is not None:
        return

    console.print(
        "[yellow]Current directory is outside the configured workspace.[/yellow]\n"
        f"  Workspace: {shell_ctx.workspace}\n"
        f"  Current directory: {shell_ctx.session_cwd}\n"
        "Authorize this directory so MindBot can use it as the default current "
        "directory for this shell session?\n"
        "[dim]This does not enable an OS-level shell sandbox.[/dim]"
    )
    choice = typer.prompt(
        "Choose [session/persist/deny]",
        default="session",
        show_default=True,
    ).strip().lower()

    if choice in {"persist", "p", "always"}:
        _persist_trusted_path(shell_ctx.config_file, shell_ctx.session_cwd)
        if str(shell_ctx.session_cwd) not in bot.config.agent.trusted_paths:
            bot.config.agent.trusted_paths.append(str(shell_ctx.session_cwd))
        shell_ctx.persisted_trusted_paths.add(shell_ctx.session_cwd)
        shell_ctx.session_cwd_authorized = True
        console.print(f"[green]Trusted and persisted:[/green] {shell_ctx.session_cwd}")
        return

    if choice in {"session", "s", "once"}:
        shell_ctx.session_trusted_paths.add(shell_ctx.session_cwd)
        shell_ctx.session_cwd_authorized = True
        console.print(f"[green]Trusted for this session:[/green] {shell_ctx.session_cwd}")
        return

    shell_ctx.session_cwd_authorized = False
    console.print(
        f"[yellow]Current directory not trusted.[/yellow] MindBot will continue using "
        f"workspace {shell_ctx.workspace}"
    )


def _build_shell_turn_tools(bot: Any, shell_ctx: _ShellSessionContext) -> list[Any]:
    """Build the tool set for one shell turn using the current trust state."""
    from mindbot.tools.file_ops import create_file_tools
    from mindbot.tools.mindbot_ops import create_mindbot_tools
    from mindbot.tools.shell_ops import create_shell_tools
    from mindbot.tools.web_ops import create_web_tools

    allowed_paths = _unique_paths(
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

def _prompt_download_model(setup: Any, console: Console) -> str | None:
    """Prompt user to select a model from recommended list to download.

    Returns:
        Selected model name or None if skipped.
    """
    from rich.console import Console

    console.print("\n[bold]Recommended models to download:[/bold]")
    for i, m in enumerate(setup.RECOMMENDED_MODELS, 1):
        marker = "[green]← 推荐[/green]" if m["name"] == setup.DEFAULT_MODEL else ""
        console.print(f"  [{i}] {m['name']} ({m['size']}) - {m['description']} {marker}")

    console.print(f"  [{len(setup.RECOMMENDED_MODELS) + 1}] Enter custom model name")
    console.print(f"  [{len(setup.RECOMMENDED_MODELS) + 2}] Skip (configure manually later)")

    choice = typer.prompt(
        "Select model to download",
        default="1",
        show_default=True,
    )

    try:
        idx = int(choice)
        if 1 <= idx <= len(setup.RECOMMENDED_MODELS):
            model = setup.RECOMMENDED_MODELS[idx - 1]["name"]
            console.print(f"[yellow]Downloading {model}...[/yellow]")
            if setup.pull_model(model):
                console.print(f"[green]✓[/green] Model {model} downloaded")
                return model
            else:
                console.print(f"[red]✗[/red] Failed to download {model}")
                console.print(f"[dim]You can download manually: ollama pull {model}[/dim]")
                return None
        elif idx == len(setup.RECOMMENDED_MODELS) + 1:
            # Custom model name
            custom = typer.prompt("Enter model name (e.g., llama3:8b)")
            if custom.strip():
                console.print(f"[yellow]Downloading {custom}...[/yellow]")
                if setup.pull_model(custom.strip()):
                    console.print(f"[green]✓[/green] Model {custom} downloaded")
                    return custom.strip()
                else:
                    console.print(f"[red]✗[/red] Failed to download {custom}")
                    return None
        else:
            console.print("[yellow]Skipping model download[/yellow]")
            return None
    except ValueError:
        console.print("[red]Invalid choice[/red]")
        return None


def _update_settings_model(config_file: Path, model: str) -> None:
    """Update both agent.model and providers model configuration.

    Args:
        config_file: Path to settings.json
        model: Model name (e.g., 'qwen3:2b')
    """
    import json

    try:
        data = json.loads(config_file.read_text(encoding="utf-8"))

        # Update agent.model with full instance/model format
        agent_data = data.setdefault("agent", {})
        agent_data["model"] = f"local-ollama/{model}"

        # Update providers.local-ollama models list
        providers = data.setdefault("providers", {})
        ollama_provider = providers.setdefault("local-ollama", {})
        ollama_provider.setdefault("type", "ollama")
        ollama_provider.setdefault("strategy", "round-robin")
        endpoints = ollama_provider.setdefault("endpoints", [])

        # Ensure at least one endpoint exists
        if not endpoints:
            endpoints.append({
                "base_url": "http://localhost:11434",
                "weight": 1,
                "models": [],
            })

        # Update or create the model entry
        models_list = endpoints[0].setdefault("models", [])
        if models_list:
            # Update existing model entry
            models_list[0]["id"] = model
            # Check if model name suggests vision capability
            if "vl" in model.lower() or "vision" in model.lower():
                models_list[0]["vision"] = True
        else:
            # Create new model entry
            models_list.append({
                "id": model,
                "role": "chat",
                "level": "medium",
                "vision": "vl" in model.lower() or "vision" in model.lower(),
            })

        config_file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception:
        # Silently ignore if settings.json cannot be updated
        pass


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
    for d in ("skills", "memory", "history", "cron", "workspace"):
        (root / d).mkdir(exist_ok=True)

    # Copy built-in skills from templates (skip if user skill already exists)
    _copy_builtin_skills(root / "skills")

    console.print(f"[green]✓[/green] Initialized workspace at {root}")

    # Ollama setup
    selected_model: str | None = None
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

                # Get local models
                local_models = setup.list_local_models()

                if local_models:
                    # User has models - let them choose
                    console.print("\n[bold]Local models found:[/bold]")
                    for i, m in enumerate(local_models, 1):
                        marker = ""
                        if m["name"] == setup.DEFAULT_MODEL:
                            marker = "[green]← 推荐[/green]"
                        console.print(f"  [{i}] {m['name']} ({m['size']}) {marker}")

                    console.print(f"  [{len(local_models) + 1}] Download a new model")
                    console.print(f"  [{len(local_models) + 2}] Skip model selection")

                    choice = typer.prompt(
                        "Select model",
                        default="1",
                        show_default=True,
                    )

                    try:
                        idx = int(choice)
                        if 1 <= idx <= len(local_models):
                            selected_model = local_models[idx - 1]["name"]
                            console.print(f"[green]✓[/green] Selected model: {selected_model}")
                        elif idx == len(local_models) + 1:
                            # Download new model
                            selected_model = _prompt_download_model(setup, console)
                        else:
                            console.print("[yellow]Skipping model selection[/yellow]")
                    except ValueError:
                        console.print("[red]Invalid choice[/red]")
                else:
                    # No local models - prompt to download
                    console.print("[yellow]⚠[/yellow] No local models found")
                    selected_model = _prompt_download_model(setup, console)

            else:
                console.print("[yellow]⚠[/yellow] Ollama not found")
                if typer.confirm("Install Ollama now?"):
                    if setup.install():
                        if setup.start_service():
                            selected_model = _prompt_download_model(setup, console)
                            if selected_model and setup.pull_model(selected_model):
                                console.print("[green]✓[/green] Ollama setup complete")
                        else:
                            console.print("[yellow]Please start Ollama manually and download a model[/yellow]")
                    else:
                        console.print("[yellow]Please install Ollama manually from https://ollama.com[/yellow]")
                else:
                    console.print("[yellow]Skipped Ollama installation[/yellow]")
                    console.print("[dim]You can install it later from https://ollama.com[/dim]")

        except Exception as e:
            console.print(f"[yellow]⚠ Ollama check failed: {e}[/yellow]")

    # Write selected model to settings.json
    if selected_model:
        _update_settings_model(config_file, selected_model)
        console.print(f"[green]✓[/green] Model {selected_model} saved to settings.json")

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

def _handle_slash_command(cmd: str, bot: Any, shell_ctx: _ShellSessionContext | None = None) -> None:
    """Dispatch slash commands in the interactive shell.

    Supported commands:
        /model                List available models (highlight current)
        /model <instance/model>   Switch to a different model
        /help                 Show available slash commands
        /status               Show bot status
        /config               Real-time config commands
    """
    parts = cmd.split()
    command = parts[0].lower()
    args = parts[1:] if len(parts) > 1 else []

    if command == "/model":
        arg = " ".join(args)
        _cmd_model(bot, arg)
    elif command == "/help":
        _cmd_help()
    elif command == "/status":
        _cmd_status(bot, shell_ctx)
    elif command == "/config":
        _cmd_config(args)
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
    console.print("  /config             Real-time config commands")
    console.print("  /config get <scope> <key>")
    console.print("  /config set <scope> <key> <value>")
    console.print("  /config auth grant <user> <tool> [--expires <sec>]")
    console.print("  /config auth check <user> <tool>")
    console.print("  /config list")
    console.print("  /help               Show this help")
    console.print("  exit, quit, bye     Exit the shell")


def _cmd_status(bot: Any, shell_ctx: _ShellSessionContext | None = None) -> None:
    """Show bot status."""
    console.print(f"  Model:    [cyan]{bot.model}[/cyan]")
    console.print(f"  Provider: [cyan]{bot.provider}[/cyan]")
    if shell_ctx is not None:
        console.print(f"  Workspace: [cyan]{shell_ctx.workspace}[/cyan]")
        console.print(f"  Current directory: [cyan]{shell_ctx.session_cwd}[/cyan]")
        console.print(f"  Effective root: [cyan]{shell_ctx.effective_root}[/cyan]")
        console.print(f"  Directory trust: [cyan]{shell_ctx.trust_status}[/cyan]")
        trusted_paths = ", ".join(str(path) for path in shell_ctx.trusted_paths) or "(none)"
        console.print(f"  Trusted paths: [cyan]{trusted_paths}[/cyan]")
        console.print(
            "  Shell policy: [cyan]"
            f"{bot.config.agent.shell_execution.policy.value}"
            "[/cyan]"
        )


def _cmd_config(args: list[str]) -> None:
    """Handle /config command in shell."""
    from mindbot.cli.config_cmd import handle_config_command
    handle_config_command(["config"] + args)


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

    shell_ctx = _resolve_shell_session_context(bot, config_file, Path.cwd())

    console.print("[bold green]MindBot Shell[/bold green] (Ctrl+C to exit)")
    console.print(f"[dim]Session: {session_id} | Model: {bot.model}[/dim]")
    console.print(f"[dim]Workspace: {shell_ctx.workspace}[/dim]")
    console.print(f"[dim]Current directory: {shell_ctx.session_cwd}[/dim]")
    _prompt_trust_session_cwd(bot, shell_ctx)
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
                _handle_slash_command(stripped, bot, shell_ctx)
                continue

            console.print("[dim]Thinking...[/dim]")
            import asyncio
            state = _ShellEventState()
            turn_tools = _build_shell_turn_tools(bot, shell_ctx)
            agent_response = asyncio.run(
                bot.chat(
                    user_input,
                    session_id=session_id,
                    tools=turn_tools,
                    on_event=lambda event: _emit_shell_event(event, state),
                )
            )
            _render_shell_response(agent_response.content, state)
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
# benchmark adapter
# ======================================================================

@app.command("toolcall15-adapter")
def toolcall15_adapter(
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind the OpenAI-compatible adapter to"),
    port: int = typer.Option(11435, "--port", help="Port to bind the OpenAI-compatible adapter to"),
    config_path: Path | None = typer.Option(
        None,
        "--config-path",
        help="Optional path to a MindBot settings.json file",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        help="Optional fixed instance/model ref exposed to ToolCall-15",
    ),
):
    """Serve an OpenAI-compatible bridge for ToolCall-15."""
    import asyncio

    from mindbot.benchmarking import serve_toolcall15_adapter

    resolved_config_path = config_path or _find_config_file()
    if resolved_config_path is None:
        console.print("[red]Error: Config not found. Run 'mindbot generate-config' first.[/red]")
        raise typer.Exit(1)

    console.print("[bold green]Starting ToolCall-15 adapter[/bold green]")
    console.print(f"  Host: {host}")
    console.print(f"  Port: {port}")
    console.print(f"  Config: {resolved_config_path}")
    if model:
        console.print(f"  Fixed model: {model}")

    try:
        asyncio.run(
            serve_toolcall15_adapter(
                host=host,
                port=port,
                config_path=resolved_config_path,
                default_model=model,
            )
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]ToolCall-15 adapter stopped[/yellow]")


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
