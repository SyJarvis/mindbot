"""斜杠命令补全器。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from prompt_toolkit.completion import Completer, Completion, CompleteEvent
from prompt_toolkit.completion.fuzzy_completer import FuzzyCompleter
from prompt_toolkit.completion.word_completer import WordCompleter
from prompt_toolkit.document import Document


@dataclass(frozen=True, slots=True)
class SlashCommand:
    """斜杠命令定义。"""

    name: str
    description: str = ""
    aliases: tuple[str, ...] = ()


class SlashCommandCompleter(Completer):
    """Fuzzy 斜杠命令补全。

    触发规则：
        - 输入 ``/`` 即触发补全
        - 空格后停止（参数阶段不补全）
        - ``Enter`` 选择补全项时同时提交命令
    """

    def __init__(self, commands: Sequence[SlashCommand]) -> None:
        self._commands = commands
        # 构建命令名列表（包含别名）
        names = []
        for cmd in commands:
            names.append(f"/{cmd.name}")
            for alias in cmd.aliases:
                names.append(f"/{alias}")
        self._fuzzy = FuzzyCompleter(
            WordCompleter(names, WORD=False),
            WORD=False,
            pattern=r"^\S+",
        )

    def get_completions(self, document: Document, complete_event: CompleteEvent):
        text = document.text_before_cursor
        # 只在输入 / 且无空格时触发
        if not text.startswith("/") or " " in text:
            return
        yield from self._fuzzy.get_completions(document, complete_event)


def get_default_slash_commands() -> list[SlashCommand]:
    """返回 MindBot 默认的斜杠命令列表。"""
    return [
        SlashCommand("model", description="List or switch models", aliases=("m",)),
        SlashCommand("help", description="Show help", aliases=("h", "?")),
        SlashCommand("status", description="Show bot status"),
        SlashCommand("config", description="Real-time config commands"),
        SlashCommand("theme", description="Switch theme (dark/light)"),
    ]
