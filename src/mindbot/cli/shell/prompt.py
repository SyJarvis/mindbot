"""ShellPrompt — PromptSession 封装，非全屏方案（参考 kimi-cli）。

职责：仅管理用户输入。
  - message 回调：── input ── 分隔线 + 光标（固定高度，不含流式内容）
  - bottom_toolbar 回调：两行状态栏
  - erase_when_done：提交后擦除 prompt 区域

流式内容由 LiveRenderer（Rich Live）独立渲染，不经过 message 区域。
因此输入框不会随流式内容移动。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable, Sequence

from prompt_toolkit import PromptSession
from prompt_toolkit.application import get_app_or_none
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style as PTKStyle

from mindbot.cli.shell.completers import SlashCommand, SlashCommandCompleter
from mindbot.cli.shell.keybindings import create_key_bindings
from mindbot.cli.shell.theme import get_active_theme, get_prompt_style
from mindbot.cli.shell.toolbar import StatusSnapshot, render_toolbar


class ShellPrompt:
    """封装 PromptSession，仅负责用户输入。

    message 固定返回分隔线（不含动态内容），确保输入框位置不变。
    """

    def __init__(
        self,
        *,
        status_provider: Callable[[], StatusSnapshot],
        slash_commands: Sequence[SlashCommand] | None = None,
    ) -> None:
        self._status_provider = status_provider

        # 键绑定
        kb = create_key_bindings()

        # 补全
        completer = SlashCommandCompleter(slash_commands) if slash_commands else None

        # 历史
        history_dir = Path.home() / ".mindbot" / "history" / "cli_history"
        history_dir.parent.mkdir(parents=True, exist_ok=True)

        self._session: PromptSession[str] = PromptSession(
            message=self._render_message,
            bottom_toolbar=self._render_toolbar,
            completer=completer,
            key_bindings=kb,
            style=get_prompt_style(),
            history=FileHistory(str(history_dir)),
            multiline=False,
            erase_when_done=True,
        )

    async def prompt(self) -> str:
        """等待用户输入，返回文本。"""
        return await self._session.prompt_async()

    # ------------------------------------------------------------------
    # 渲染回调 — 固定布局，不含动态内容
    # ------------------------------------------------------------------

    def _render_message(self) -> FormattedText:
        """输入区：分隔线 + > 提示符（固定高度）。"""
        app = get_app_or_none()
        columns = app.output.get_size().columns if app else 80
        theme = get_active_theme()

        # 分隔线
        return FormattedText([
            ("class:input.separator", theme.separator * columns),
            ("", "\n"),
            ("class:input", "> "),
        ])

    def _render_toolbar(self) -> FormattedText:
        """底部工具栏渲染回调。"""
        app = get_app_or_none()
        columns = app.output.get_size().columns if app else 80
        status = self._status_provider()
        return render_toolbar(status, columns)
