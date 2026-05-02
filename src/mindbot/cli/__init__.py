"""MindBot CLI 入口：typer app 定义 + 命令注册。

模块结构：
    cli/__init__.py           typer app + 命令注册
    cli/_shared.py            共享工具（console 实例、find_config_file）
    cli/shell/
        __init__.py           Shell 类 + shell_command 入口
        prompt.py             ShellPrompt（PromptSession 封装 + 动态内容 + 刷新）
        context.py            会话上下文、目录信任、工具构建
        visualize.py          LiveRenderer + AppRenderer（Wire 事件渲染）
        slash.py              slash 命令分发（/model, /help, /status, /config, /theme）
        completers.py         斜杠命令 fuzzy 补全
        keybindings.py        自定义键绑定（多行输入、编辑器、粘贴）
        toolbar.py            底部工具栏渲染（model/workspace/context/tips）
        console.py            Rich↔prompt_toolkit ANSI 桥接
        theme.py              主题管理（dark/light）
        toast.py              非侵入式 Toast 通知
        startup.py            欢迎界面
    cli/commands/
        onboard.py            generate-config / onboard 命令
        chat.py               chat 命令
        serve.py              serve 命令
        status.py             status 命令
        benchmark.py          toolcall15-adapter 命令
        config_show.py        config show / validate 子命令
        config_cmd.py         实时配置系统（get/set/auth）
"""

import typer

from mindbot import __version__, __logo__
from mindbot.cli._shared import console

app = typer.Typer(
    name="mindbot",
    help=f"{__logo__}\nMindBot - AI Assistant",
    no_args_is_help=False,
)


def version_callback(value: bool):
    if value:
        console.print(f"MindBot v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(None, "--version", "-v", callback=version_callback, is_eager=True),  # noqa: ARG001
):
    """MindBot CLI."""
    pass


# --- 命令注册 ---

from mindbot.cli.commands.onboard import onboard
from mindbot.cli.commands.chat import chat
from mindbot.cli.commands.serve import serve
from mindbot.cli.commands.status import status
from mindbot.cli.commands.benchmark import toolcall15_adapter
from mindbot.cli.commands.config_show import config_app
from mindbot.cli.shell import shell_command

app.command("shell")(shell_command)
app.command("generate-config")(onboard)
app.command("onboard")(onboard)
app.command()(chat)
app.command()(serve)
app.command()(status)
app.command("toolcall15-adapter")(toolcall15_adapter)
app.add_typer(config_app, name="config")


if __name__ == "__main__":
    app()
