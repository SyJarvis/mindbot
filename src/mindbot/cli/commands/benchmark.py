"""toolcall15-adapter 命令。"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from mindbot.cli._shared import console, find_config_file


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
) -> None:
    """启动 ToolCall-15 的 OpenAI 兼容桥接。"""
    import asyncio

    from mindbot.benchmarking import serve_toolcall15_adapter

    resolved_config_path = config_path or find_config_file()

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
