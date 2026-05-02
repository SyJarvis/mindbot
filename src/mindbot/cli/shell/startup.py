"""欢迎界面 — 纯文本左对齐，不用 Rich Panel。"""

from __future__ import annotations

import os

from rich.console import Group
from rich.text import Text


def build_welcome_banner(
    *,
    model_name: str,
    workspace: str,
    session_id: str,
) -> Group:
    """构建欢迎 Banner — 纯文本左对齐。"""
    lines: list[Text] = []

    lines.append(Text("M I N D B O T", style="bold cyan"))
    lines.append(Text("AI Assistant Shell", style="dim"))
    lines.append(Text(""))
    lines.append(Text(f"Session: {_truncate(session_id, 40)}", style="dim"))
    lines.append(Text(f"Model:   {_truncate(model_name, 40)}", style="dim"))
    lines.append(Text(f"CWD:     {_shorten(workspace, 40)}", style="dim"))
    lines.append(Text(""))
    lines.append(Text("/help | Ctrl-C exit | Alt-Enter newline", style="dim italic"))

    return Group(*lines)


def _shorten(path: str, max_len: int = 40) -> str:
    """缩短路径为 ~ 形式。"""
    home = os.path.expanduser("~")
    if path.startswith(home):
        path = "~" + path[len(home):]
    return _truncate(path, max_len)


def _truncate(text: str, max_len: int) -> str:
    """截断过长文本。"""
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text
