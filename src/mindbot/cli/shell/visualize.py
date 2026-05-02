"""Wire 消费者 + 渲染器。

StreamRenderer: 逐行打印到 scrollback，所有内容同级、FIFO。
  > 用户输入
  Thinking...
  ⚙ ReadFile src/xxx
  ✓ ReadFile
  ⚙ Shell ls -la
  ✓ Shell
  AI 回复原始文本...
"""

from __future__ import annotations

from typing import Any

from rich.console import Console

from mindbot.agent.models import AgentEvent, EventType


def _format_tool_args(arguments: str | dict | None, max_len: int = 60) -> str:
    """从 JSON arguments 中提取关键参数，返回简短摘要。"""
    if not arguments:
        return ""
    if isinstance(arguments, dict):
        args = arguments
    else:
        try:
            import json
            args = json.loads(arguments)
        except Exception:
            return arguments[:max_len] + ("..." if len(arguments) > max_len else "")
    if not isinstance(args, dict) or not args:
        return ""
    keys = ["file_path", "path", "command", "query", "message", "url", "directory", "cwd"]
    for key in keys:
        if key in args:
            val = str(args[key])
            if len(val) > max_len:
                val = val[:max_len - 3] + "..."
            return val
    first_val = str(next(iter(args.values())))
    if len(first_val) > max_len:
        first_val = first_val[:max_len - 3] + "..."
    return first_val


# ---------------------------------------------------------------------------
# StreamRenderer — 逐行输出，所有内容同级 FIFO
# ---------------------------------------------------------------------------

class StreamRenderer:
    """逐行打印到 scrollback。用户输入、工具状态、AI 回复同级 FIFO。

    不使用 Rich Live，所有内容通过 console.print() 直接输出到终端。
    """

    def __init__(self, *, console: Console | None = None) -> None:
        self._console = console or Console()
        self._text_buffer = ""
        self._had_thinking = False
        self._error_printed = False

    # ---- 生命周期（与 LiveRenderer 接口兼容）----

    def start(self) -> None:
        """无操作（StreamRenderer 不需要启动）。"""

    def stop(self) -> None:
        """无操作。"""

    # ---- 事件处理 ----

    def handle_event(self, event: AgentEvent) -> None:
        """处理事件，逐行输出到 scrollback。"""
        event_type = event.type

        if event_type == EventType.THINKING:
            if not self._had_thinking:
                self._flush_text()
                self._console.print("  Thinking...", style="dim")
                self._had_thinking = True

        elif event_type == EventType.TOOL_EXECUTING:
            self._flush_text()
            tool = event.data.get("tool_name", "unknown")
            args_hint = _format_tool_args(event.data.get("arguments"))
            label = f"  \u2699 {tool}"
            if args_hint:
                label += f"  {args_hint}"
            self._console.print(label, style="dim")

        elif event_type == EventType.TOOL_RESULT:
            self._flush_text()
            tool = event.data.get("tool_name", "unknown")
            self._console.print(f"  \u2713 {tool}", style="dim green")

        elif event_type == EventType.DELTA:
            content = event.data.get("content", "")
            if content:
                self._text_buffer += content
                # 有完整行就输出（保留换行）
                while "\n" in self._text_buffer:
                    line, self._text_buffer = self._text_buffer.split("\n", 1)
                    self._console.print(line)

        elif event_type == EventType.ERROR:
            self._flush_text()
            msg = event.data.get("message", "Unknown error")
            self._console.print(f"  Error: {msg}", style="bold red")
            self._error_printed = True

        elif event_type == EventType.COMPLETE:
            self._flush_text()

    def render_tick(self) -> None:
        """无操作（StreamRenderer 在 handle_event 中实时输出）。"""

    def finalize(self) -> None:
        """刷新剩余文本，留空行分隔。"""
        self._flush_text()
        self._console.print()  # 空行

    # ---- 内部 ----

    def _flush_text(self) -> None:
        """输出缓冲区中的剩余文本。"""
        if self._text_buffer:
            self._console.print(self._text_buffer)
            self._text_buffer = ""

