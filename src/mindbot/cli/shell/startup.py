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


def build_welcome_lines(
    *,
    model_name: str,
    workspace: str,
    session_id: str,
    columns: int = 80,
) -> list[tuple[str, str]]:
    """构建欢迎 Banner 的 FormattedText 片段列表（向后兼容）。"""
    w = min(max(columns, 40), 60)
    inner = w - 2

    lines: list[tuple[str, str]] = []

    # 顶边
    lines.append(("class:banner.border", "+" + "-" * inner + "+"))

    # Logo
    logo = "M I N D B O T"
    pad_l = (inner - len(logo)) // 2
    pad_r = inner - pad_l - len(logo)
    lines.append(("class:banner.title", "|" + " " * pad_l + logo + " " * pad_r + "|"))

    # 副标题
    sub = "AI Assistant Shell"
    pad_l = (inner - len(sub)) // 2
    pad_r = inner - pad_l - len(sub)
    lines.append(("class:banner.title", "|" + " " * pad_l + sub + " " * pad_r + "|"))

    # 空行
    lines.append(("class:banner.border", "|" + " " * inner + "|"))

    # 信息行
    info = [
        ("Session ", _truncate(session_id, inner - 14)),
        ("Model  ", _truncate(model_name, inner - 14)),
        ("CWD    ", _shorten(workspace, inner - 14)),
    ]
    for label, value in info:
        row = f"|  {label}: {value}"
        row = row.ljust(w - 1) + "|"
        lines.append(("class:banner.label", row))

    # 空行
    lines.append(("class:banner.border", "|" + " " * inner + "|"))

    # 提示行
    tips = "/help | Ctrl-C exit | Alt-Enter newline"
    tip_pad_l = (inner - len(tips)) // 2
    tip_pad_r = inner - tip_pad_l - len(tips)
    lines.append(("class:banner.tip", "|" + " " * tip_pad_l + tips + " " * tip_pad_r + "|"))

    # 底边
    lines.append(("class:banner.border", "+" + "-" * inner + "+"))

    # 空行分隔
    lines.append(("", ""))

    return lines


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
