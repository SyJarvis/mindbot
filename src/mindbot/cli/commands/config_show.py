"""config show / validate 子命令。"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from mindbot.cli._shared import console, find_config_file

config_app = typer.Typer(help="Manage configuration")


@config_app.command("show")
def config_show() -> None:
    """显示当前配置。"""
    config_file = find_config_file()
    if config_file:
        try:
            text = config_file.read_text(encoding="utf-8")
            syntax = Syntax(text, "json")
            panel = Panel(syntax, title=f"Configuration: {config_file}", border_style="green")
            console.print(panel)
        except Exception as e:
            console.print(f"[red]Error reading config: {e}[/red]")
            raise typer.Exit(1)
    else:
        from mindbot.config.loader import load_config
        import json as _json
        config = load_config()
        text = _json.dumps(config.model_dump(mode="json"), indent=2, ensure_ascii=False)
        syntax = Syntax(text, "json")
        panel = Panel(syntax, title="Effective configuration (defaults + env)", border_style="green")
        console.print(panel)


@config_app.command("validate")
def config_validate() -> None:
    """验证当前配置。"""
    from mindbot.config.loader import load_config

    config_file = find_config_file()
    try:
        config = load_config(config_file)

        src = str(config_file) if config_file else "defaults.json"
        console.print(f"[green]✓[/green] Config is valid: {src}")
        console.print(f"  Agent model: {config.agent.model}")
        console.print(f"  Providers: {', '.join(config.providers.keys()) or '(none)'}")
        console.print(f"  Routing: {'auto' if config.routing.auto else 'manual'}")
        console.print(f"  Memory: {config.memory.storage_path}")

        # 验证 provider 类型
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
