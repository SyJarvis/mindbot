"""generate-config / onboard 命令。"""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from mindbot import __version__
from mindbot.cli._shared import console

app = typer.Typer(help="配置初始化")


def _read_template(name: str) -> str:
    """从 mindbot.templates 包读取模板文件。"""
    ref = resources.files("mindbot.templates").joinpath(name)
    return ref.read_text(encoding="utf-8")


def _copy_tree(src, dst: Path) -> None:
    """递归复制目录树。"""
    dst.mkdir(parents=True, exist_ok=True)
    for entry in src.iterdir():
        child = dst / entry.name
        if entry.is_dir():
            _copy_tree(entry, child)
        else:
            child.write_bytes(entry.read_bytes())


def _copy_builtin_skills(skills_dir: Path) -> None:
    """从模板复制内置技能到 skills_dir，跳过已存在的。"""
    templates = resources.files("mindbot.templates").joinpath("skills")
    for skill_entry in templates.iterdir():
        if not skill_entry.is_dir():
            continue
        target = skills_dir / skill_entry.name
        if target.exists():
            continue
        _copy_tree(skill_entry, target)


def _prompt_download_model(setup: Any, console: Console) -> str | None:
    """提示用户从推荐列表中选择模型下载。

    Returns:
        选中的模型名称，或 None 表示跳过。
    """
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
            # 自定义模型名称
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
    """更新 agent.model 和 providers 模型配置。"""
    import json

    try:
        data = json.loads(config_file.read_text(encoding="utf-8"))

        # 使用完整 instance/model 格式更新 agent.model
        agent_data = data.setdefault("agent", {})
        agent_data["model"] = f"local-ollama/{model}"

        # 更新 providers.local-ollama 模型列表
        providers = data.setdefault("providers", {})
        ollama_provider = providers.setdefault("local-ollama", {})
        ollama_provider.setdefault("type", "ollama")
        ollama_provider.setdefault("strategy", "round-robin")
        endpoints = ollama_provider.setdefault("endpoints", [])

        # 确保至少一个端点存在
        if not endpoints:
            endpoints.append({
                "base_url": "http://localhost:11434",
                "weight": 1,
                "models": [],
            })

        # 更新或创建模型条目
        models_list = endpoints[0].setdefault("models", [])
        if models_list:
            models_list[0]["id"] = model
            if "vl" in model.lower() or "vision" in model.lower():
                models_list[0]["vision"] = True
        else:
            models_list.append({
                "id": model,
                "role": "chat",
                "level": "medium",
                "vision": "vl" in model.lower() or "vision" in model.lower(),
            })

        config_file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception:
        # 如果无法更新 settings.json 则静默忽略
        pass


def onboard(
    skip_ollama: bool = typer.Option(
        False, "--skip-ollama", help="Skip Ollama installation check"
    ),
) -> None:
    """生成默认配置文件并初始化工作区。"""
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

    # 创建工作区子目录
    for d in ("skills", "memory", "history", "cron", "workspace", "data"):
        (root / d).mkdir(exist_ok=True)

    # 从模板复制内置技能（如果用户技能已存在则跳过）
    _copy_builtin_skills(root / "skills")

    console.print(f"[green]✓[/green] Initialized workspace at {root}")

    # Ollama 设置
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

                # 获取本地模型
                local_models = setup.list_local_models()

                if local_models:
                    # 用户有模型 - 让他们选择
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
                            # 下载新模型
                            selected_model = _prompt_download_model(setup, console)
                        else:
                            console.print("[yellow]Skipping model selection[/yellow]")
                    except ValueError:
                        console.print("[red]Invalid choice[/red]")
                else:
                    # 没有本地模型 - 提示下载
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

    # 写入选中模型到 settings.json
    if selected_model:
        _update_settings_model(config_file, selected_model)
        console.print(f"[green]✓[/green] Model {selected_model} saved to settings.json")

    console.print("\n[bold]Next steps:[/bold]")
    console.print("  1. Edit [cyan]~/.mindbot/settings.json[/cyan] to configure providers")
    console.print("  2. Edit [cyan]~/.mindbot/SYSTEM.md[/cyan] to customise the system prompt")
    console.print("  3. Run  [cyan]mindbot serve[/cyan]")
