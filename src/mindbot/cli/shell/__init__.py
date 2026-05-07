"""MindBot 交互式 Shell 模式。

非全屏 PromptSession + Rich Live 架构：
  - PromptSession：固定输入框 + toolbar（不随内容移动）
  - Rich Live：流式内容渲染（独立于 PromptSession）
  - erase_when_done：提交后擦除 prompt，内容写入 scrollback
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.text import Text

from mindbot.agent.models import EventType
from mindbot.cli._shared import find_config_file
from mindbot.cli.shell.context import (
    ShellSessionContext,
    resolve_shell_session_context,
    prompt_trust_session_cwd_with_natural_language,
    build_shell_turn_tools,
)
from mindbot.cli.shell.prompt import ShellPrompt
from mindbot.cli.shell.slash import handle_slash_command
from mindbot.cli.shell.completers import get_default_slash_commands
from mindbot.cli.shell.toolbar import StatusSnapshot, rotate_tip
from mindbot.cli.shell.visualize import StreamRenderer
from mindbot.wire import Wire

console = Console()


@dataclass
class _TurnResult:
    """一次 agent turn 的执行结果。"""

    response: Any  # AgentResponse | None
    interrupted: bool = False


class Shell:
    """MindBot 交互式 Shell。

    输入框固定在底部（PromptSession），流式内容由 Rich Live 独立渲染。
    输入框不会随流式内容移动。
    """

    def __init__(
        self,
        bot: Any,
        config_file: Path,
        session_id: str = "default",
    ):
        self.bot = bot
        self.config_file = config_file
        self.session_id = session_id
        self.shell_ctx: ShellSessionContext | None = None
        self.permission_manager: Any | None = None
        self._prompt: ShellPrompt | None = None
        self._chat_task: asyncio.Task | None = None

    async def run(self) -> None:
        """运行交互式 shell 主循环。"""
        from mindbot.permissions import PermissionManager

        self.shell_ctx = resolve_shell_session_context(self.bot, self.config_file, Path.cwd())

        # 初始化权限管理器
        config_data = json.loads(self.config_file.read_text(encoding="utf-8"))
        self.permission_manager = PermissionManager(config=config_data, config_path=self.config_file)
        self.shell_ctx.permission_manager = self.permission_manager

        # 处理目录授权
        await prompt_trust_session_cwd_with_natural_language(self.permission_manager, self.shell_ctx)

        # 创建 ShellPrompt
        slash_commands = get_default_slash_commands()
        self._prompt = ShellPrompt(
            status_provider=self._get_status,
            slash_commands=slash_commands if slash_commands else None,
        )

        # 欢迎横幅 → scrollback
        from mindbot.cli.shell.startup import build_welcome_banner
        console.print(
            build_welcome_banner(
                model_name=self.bot.model,
                workspace=str(self.shell_ctx.workspace),
                session_id=self.session_id,
            )
        )

        # 主循环
        while True:
            try:
                user_input = await self._prompt.prompt()
            except KeyboardInterrupt:
                continue
            except EOFError:
                break

            stripped = user_input.strip()
            if not stripped:
                continue

            # 退出命令
            if stripped.lower() in ("exit", "quit", "bye"):
                console.print(Text("Goodbye!", style="dim"))
                break

            # Slash 命令
            if stripped.startswith("/"):
                await handle_slash_command(stripped, self.bot, self.shell_ctx)
                continue

            # 用户输入 → scrollback
            console.print()
            console.print(Text(f"> {stripped}", style="bold cyan"))
            rotate_tip()

            # 执行 agent turn（Rich Live 渲染流式内容）
            try:
                await self._run_agent_turn(stripped)
            except KeyboardInterrupt:
                # Ctrl+C 中断流式输出
                if self._chat_task and not self._chat_task.done():
                    self._chat_task.cancel()
                console.print(Text("\n[interrupted]", style="yellow"))
                console.print()

    # ------------------------------------------------------------------
    # Agent Turn（Wire + Rich Live）
    # ------------------------------------------------------------------

    async def _run_agent_turn(self, message: str) -> None:
        """Wire 路径：chat() → Wire → StreamRenderer（逐行输出）→ scrollback。"""
        wire = Wire()
        turn_tools = build_shell_turn_tools(self.bot, self.shell_ctx)
        renderer = StreamRenderer(console=console)
        renderer.start()

        async def _chat_and_close() -> Any:
            try:
                return await self.bot.chat(
                    message,
                    session_id=self.session_id,
                    tools=turn_tools,
                    on_event=wire.send,
                )
            finally:
                wire.close()

        self._chat_task = asyncio.create_task(_chat_and_close())

        try:
            async for event in wire.receive():
                renderer.handle_event(event)
                renderer.render_tick()

                if event.type == EventType.PERMISSION_REQUEST:
                    pass
        except asyncio.CancelledError:
            pass
        finally:
            renderer.finalize()
            renderer.stop()
            self._chat_task = None

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------

    def _get_status(self) -> StatusSnapshot:
        """获取当前状态快照，供状态栏渲染。"""
        workspace = str(self.shell_ctx.workspace) if self.shell_ctx else "."
        responding = self._chat_task is not None and not self._chat_task.done()

        context_tokens = self.bot.get_conversation_token_count(self.session_id)
        max_context_tokens = self.bot.config.context.max_tokens
        context_usage = context_tokens / max_context_tokens if max_context_tokens > 0 else 0.0

        return StatusSnapshot(
            model_name=self.bot.model,
            workspace=workspace,
            session_id=self.session_id,
            thinking=responding,
            context_usage=context_usage,
            context_tokens=context_tokens,
            max_context_tokens=max_context_tokens,
        )


def shell_command(
    session_id: str = typer.Option("default", "--session", "-s", help="Session ID"),
) -> None:
    """启动交互式 shell 模式。"""

    async def _run():
        config_file = find_config_file()
        if not config_file:
            console.print("[red]Error: Config not found. Run 'mindbot generate-config' first.[/red]")
            raise typer.Exit(1)

        try:
            from mindbot import MindBot
            bot = MindBot()
        except Exception as e:
            console.print(f"[red]Error initializing bot: {e}[/red]")
            raise typer.Exit(1)

        shell = Shell(bot, config_file, session_id=session_id)
        await shell.run()

    asyncio.run(_run())
