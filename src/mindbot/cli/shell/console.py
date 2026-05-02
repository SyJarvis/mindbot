"""Rich ↔ prompt_toolkit 桥接。"""

from __future__ import annotations

import re
from io import StringIO

from rich.console import Console
from rich.theme import Theme

# 中性 Markdown 主题，避免与 prompt_toolkit 样式冲突
NEUTRAL_MARKDOWN_THEME = Theme(
    {
        "markdown.paragraph": "none",
        "markdown.block_quote": "none",
        "markdown.code": "none",
        "markdown.code_block": "none",
        "status.spinner": "none",
    },
    inherit=True,
)

# prompt_toolkit 无法解析 OSC 8 超链接，需要包裹为 ZeroWidthEscape
_OSC8_RE = re.compile(r"\x1b\]8;[^\x07\x1b]*(?:\x1b\\|\x07)")


def render_to_ansi(renderable, *, columns: int) -> str:
    """将 Rich renderable 渲染为 ANSI 字符串，供 prompt_toolkit 集成使用。

    Args:
        renderable: Rich 可渲染对象。
        columns: 终端宽度。

    Returns:
        ANSI 字符串，OSC 8 超链接已包裹为 ZeroWidthEscape。
    """
    buf = StringIO()
    temp = Console(
        file=buf,
        force_terminal=True,
        width=max(20, columns),
        theme=NEUTRAL_MARKDOWN_THEME,
        highlight=False,
    )
    temp.print(renderable, end="")
    result = buf.getvalue()
    # 包裹 OSC 8 为 ZeroWidthEscape 标记
    return _OSC8_RE.sub(lambda m: f"\x01{m.group()}\x02", result)
