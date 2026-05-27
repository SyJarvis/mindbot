"""MindBot 交互式 Shell 模式。

全屏 TUI（codex-inspired）：
  - 顶部：可滚动消息区域（对话历史 + 流式输出）
  - 底部固定：状态栏 + 输入框
  - 所有区域始终可见，不会擦除消失
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from mindbot.agent.models import EventType
from mindbot.cli._shared import find_config_file
from mindbot.cli.shell.toolbar import StatusSnapshot, rotate_tip
from mindbot.cli.shell.slash import handle_slash_command
from mindbot.cli.shell.context import (
    ShellSessionContext,
    resolve_shell_session_context,
    prompt_trust_session_cwd_with_natural_language,
    build_shell_turn_tools,
)
from mindbot.wire import Wire
from mindbot.logging import logger

console = Console()


class Shell:
    """MindBot 交互式 Shell — 全屏 TUI 模式。

    布局（自上而下）：
        [可滚动消息区域]
        ────────────────
        [状态栏 2 行]
        ────────────────
        > [输入框]
    """

    def __init__(
        self,
        bot: Any,
        config_file: Path | None,
        session_id: str = "default",
    ):
        self.bot = bot
        self.config_file = config_file
        self.session_id = session_id
        self.shell_ctx: ShellSessionContext | None = None
        self.permission_manager: Any | None = None
        self._chat_task: asyncio.Task | None = None
        self._last_error: Exception | None = None
        self._turn_count: int = 0
        self._tui: Any = None
        self._tool_starts: dict[str, float] = {}
        self._text_buffer: Any = ""

    async def run(self) -> None:
        """运行交互式 shell 主循环。"""
        from mindbot.permissions import PermissionManager

        self.shell_ctx = resolve_shell_session_context(self.bot, self.config_file, Path.cwd())
        self.shell_ctx.session_id = self.session_id

        if self.config_file:
            config_data = json.loads(self.config_file.read_text(encoding="utf-8"))
            self.permission_manager = PermissionManager(config=config_data, config_path=self.config_file)
        else:
            config_data = self.bot.config.model_dump(mode="json")
            self.permission_manager = PermissionManager(config=config_data, config_path=None)
        self.shell_ctx.permission_manager = self.permission_manager

        await prompt_trust_session_cwd_with_natural_language(self.permission_manager, self.shell_ctx)

        # ── Build TUI app ──────────────────────────────────────────────────
        from mindbot.cli.shell.completers import get_default_slash_commands
        from mindbot.cli.shell.tui import TuiApp
        slash_cmds = get_default_slash_commands()
        command_names = [c.name for c in slash_cmds] if slash_cmds else None

        self._tui = TuiApp(
            status_provider=self._get_status,
            on_submit=self._on_tui_submit,
            slash_commands=command_names,
        )

        # ── Welcome banner → TUI message area ───────────────────────────────
        from mindbot.cli.shell.startup import build_welcome_banner
        banner = build_welcome_banner(
            model_name=self.bot.model,
            workspace=str(self.shell_ctx.workspace),
            session_id=self.session_id,
        )
        welcome_lines: list[tuple[str, str]] = []
        for item in banner.renderables:
            plain = item.plain if hasattr(item, "plain") else str(item)
            style = str(item.style) if hasattr(item, "style") and item.style else ""
            # Map Rich styles to prompt_toolkit class names
            style_map = {
                "bold cyan": "class:welcome-title",
                "dim": "class:welcome-dim",
                "dim italic": "class:welcome-dim",
            }
            ptk_style = style_map.get(style, "class:dim")
            welcome_lines.append((plain, ptk_style))
        self._tui.add_welcome(welcome_lines)

        # Run the full-screen TUI (blocks until exit)
        await self._tui.run()

    # ── Callbacks ──────────────────────────────────────────────────────────

    async def _on_tui_submit(self, text: str) -> None:
        """Called when user presses Enter in the TUI input bar."""
        stripped = text.strip()
        if not stripped:
            return

        # Exit commands
        if stripped.lower() in ("exit", "quit", "bye"):
            self._tui.exit()
            return

        # Slash commands
        if stripped.startswith("/"):
            try:
                await handle_slash_command(stripped, self.bot, self.shell_ctx)
            except Exception:
                pass
            return

        # Reset interrupt flag
        self._tui.reset_interrupted()

        # User input → message area
        self._tui.add_user_input(stripped)
        rotate_tip()

        # Run agent turn
        try:
            await self._run_tui_turn(stripped)
        except asyncio.CancelledError:
            self._tui.add_interrupted()

    async def _run_tui_turn(self, message: str) -> None:
        """Run one agent turn, piping events into the TUI message area."""
        self._turn_count += 1
        turn_start = time.monotonic()
        self._tool_starts.clear()
        self._text_buffer = _TuiTextState()

        wire = Wire()
        turn_tools = build_shell_turn_tools(self.bot, self.shell_ctx)
        tokens_before = self.bot.get_conversation_token_count(self.session_id)

        async def _chat_and_close() -> Any:
            try:
                return await self.bot.chat(
                    message,
                    session_id=self.session_id,
                    tools=turn_tools,
                    on_event=wire.send,
                )
            except Exception as exc:
                self._last_error = exc
            finally:
                wire.close()

        self._chat_task = asyncio.create_task(_chat_and_close())
        _had_thinking = False

        try:
            async for event in wire.receive():
                # Check for Ctrl-C interrupt
                if self._tui.interrupted and self._chat_task and not self._chat_task.done():
                    self._chat_task.cancel()

                self._text_buffer, _had_thinking = _handle_tui_event(
                    self._tui, event, self._tool_starts, self._text_buffer,
                    had_thinking=_had_thinking,
                )
                # Yield to event loop every few events so TUI can redraw
                await asyncio.sleep(0.001)

            if self._last_error is not None:
                raise self._last_error
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(str(e))
            self._tui.add_error(str(e))
        finally:
            self._chat_task = None
            self._last_error = None
            self._tool_starts.clear()

            elapsed_sec = time.monotonic() - turn_start
            tokens_after = self.bot.get_conversation_token_count(self.session_id)
            tokens_used = max(0, tokens_after - tokens_before)
            max_tokens = self.bot.config.context.max_tokens
            pct = (tokens_after / max_tokens * 100) if max_tokens > 0 else 0
            self._tui.add_turn_summary(elapsed_sec, tokens_used, pct)

    # ── Status ─────────────────────────────────────────────────────────────

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
            queued_count=0,
        )


# ── Event handler (module-level, stateless) ─────────────────────────────────

@dataclass
class _TuiTextState:
    pending_line: str = ""
    rendered_text: str = ""

    def append_event_content(self, content: str) -> None:
        delta = self._normalize(content)
        if not delta:
            return
        self.rendered_text += delta
        self.pending_line += delta

    def _normalize(self, content: str) -> str:
        if not self.rendered_text:
            return content
        if content.startswith(self.rendered_text):
            return content[len(self.rendered_text):]
        if self.rendered_text.startswith(content):
            return ""
        return content

    def pop_complete_line(self) -> str | None:
        if "\n" not in self.pending_line:
            return None
        line, self.pending_line = self.pending_line.split("\n", 1)
        return line

    def clear_pending_line(self) -> None:
        self.pending_line = ""


def _handle_tui_event(
    tui: Any,
    event: Any,
    tool_starts: dict[str, float],
    text_buffer: Any,
    *,
    had_thinking: bool = False,
) -> tuple[_TuiTextState, bool]:
    """Convert a single AgentEvent into TUI message lines.

    Returns (updated_text_buffer, had_thinking).
    """
    if not isinstance(text_buffer, _TuiTextState):
        text_buffer = _TuiTextState(pending_line=text_buffer or "", rendered_text=text_buffer or "")
    event_type = event.type

    if event_type == EventType.THINKING:
        tui.finalize_delta()
        if not had_thinking:
            tui.add_thinking()
            had_thinking = True

    elif event_type == EventType.TOOL_EXECUTING:
        tui.finalize_delta()
        tool = event.data.get("tool_name", "unknown")
        args_hint = _tool_args_hint(event.data.get("arguments"))
        tool_starts[tool] = time.monotonic()
        tui.add_tool_start(tool, args_hint)

    elif event_type == EventType.TOOL_RESULT:
        tool = event.data.get("tool_name", "unknown")
        elapsed_ms = 0
        if tool in tool_starts:
            elapsed_ms = int((time.monotonic() - tool_starts.pop(tool)) * 1000)
        tui.add_tool_result(elapsed_ms)

    elif event_type == EventType.DELTA:
        content = event.data.get("content", "")
        if content:
            text_buffer.append_event_content(content)
            while (line := text_buffer.pop_complete_line()) is not None:
                tui.add_stream_line(line)
            # Ongoing partial line — replace previous partial
            if text_buffer.pending_line:
                tui.upsert_delta(text_buffer.pending_line)

    elif event_type == EventType.ERROR:
        tui.finalize_delta()
        msg = event.data.get("message", "Unknown error")
        tui.add_error(msg)

    elif event_type == EventType.COMPLETE:
        tui.finalize_delta()
        text_buffer.clear_pending_line()

    return text_buffer, had_thinking


def _tool_args_hint(arguments: str | dict | None) -> str:
    if not arguments:
        return ""
    if isinstance(arguments, dict):
        args = arguments
    else:
        try:
            args = json.loads(arguments)
        except Exception:
            return str(arguments)[:60]
    if not isinstance(args, dict) or not args:
        return ""
    keys = ["file_path", "path", "command", "query", "message", "url", "directory", "cwd"]
    for key in keys:
        if key in args:
            val = str(args[key])
            return val[:60] + ("..." if len(val) > 60 else "")
    first_val = str(next(iter(args.values())))
    return first_val[:60] + ("..." if len(first_val) > 60 else "")


# ── CLI entry ──────────────────────────────────────────────────────────────

def shell_command(
    session_id: str = typer.Option("default", "--session", "-s", help="Session ID"),
) -> None:
    """启动交互式 shell 模式（全屏 TUI）。"""

    async def _run():
        config_file = find_config_file()

        try:
            from mindbot import MindBot
            bot = MindBot()
        except Exception as e:
            console.print(f"[red]Error initializing bot: {e}[/red]")
            raise typer.Exit(1)

        shell = Shell(bot, config_file, session_id=session_id)
        await shell.run()

    asyncio.run(_run())
