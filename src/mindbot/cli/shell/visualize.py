"""Wire 消费者 + 渲染器。

StreamRenderer: 逐行打印到 scrollback，所有内容同级、FIFO。
  > 用户输入
  Thinking...
  ⚙ ReadFile src/xxx ✓
  ⚙ Shell ls -la ✓
  AI 回复原始文本...

LiveRenderer: 用小区域 Rich Live 渲染，内容区显示最新几行 + 底部状态栏。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from rich.console import Console
from rich.text import Text

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
        self._tool_starts: dict[str, float] = {}

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
            self._tool_starts[tool] = time.monotonic()
            self._console.print(label, style="dim", end="")

        elif event_type == EventType.TOOL_RESULT:
            tool = event.data.get("tool_name", "unknown")
            elapsed_ms = 0
            if tool in self._tool_starts:
                elapsed_ms = int((time.monotonic() - self._tool_starts.pop(tool)) * 1000)
            timing = f" {elapsed_ms}ms" if elapsed_ms > 0 else ""
            self._console.print(f" \u2713{timing}", style="dim green")

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


# ---------------------------------------------------------------------------
# LiveRenderer — 小窗口 Live（最近 N 行内容 + 底部状态栏）
# ---------------------------------------------------------------------------

_MAX_PREVIEW_LINES = 5

class LiveRenderer:
    """用小窗口 Rich Live 渲染流式内容 + 状态栏。

    Live 使用 ``screen=False``，只占用底部少量行，
    历史记录保持在 scrollback 中不被刷掉。

    内容区最多显示最近 ``_MAX_PREVIEW_LINES`` 行，
    回复结束后所有内容写入 scrollback。
    """

    _REFRESH_MIN_INTERVAL = 0.06  # seconds

    def __init__(
        self,
        *,
        console: Console | None = None,
        status_provider: Callable[[], Any] | None = None,
    ) -> None:
        self._console = console or Console()
        self._status_provider = status_provider
        self._lines: list[Text] = []
        self._text_buffer = ""
        self._had_thinking = False
        self._tool_starts: dict[str, float] = {}
        self._live: Any | None = None
        self._columns = 80
        self._dirty = False
        self._last_refresh = 0.0

    # ---- 生命周期 ----

    def start(self) -> None:
        import shutil
        self._columns = shutil.get_terminal_size().columns

        from rich.live import Live
        self._live = Live(
            self._build_renderable(),
            console=self._console,
            screen=False,
            transient=True,
            auto_refresh=False,
        )
        self._live.start()

    def stop(self) -> None:
        if self._live is not None:
            self._live.stop()
            self._live = None

    # ---- 事件处理 ----

    def handle_event(self, event: "AgentEvent") -> None:
        event_type = event.type

        if event_type == EventType.THINKING:
            if not self._had_thinking:
                self._flush_text()
                self._lines.append(Text("  Thinking...", style="dim"))
                self._had_thinking = True
                self._dirty = True

        elif event_type == EventType.TOOL_EXECUTING:
            self._flush_text()
            tool = event.data.get("tool_name", "unknown")
            args_hint = _format_tool_args(event.data.get("arguments"))
            label = f"  \u2699 {tool}"
            if args_hint:
                label += f"  {args_hint}"
            self._tool_starts[tool] = time.monotonic()
            self._lines.append(Text(label, style="dim"))
            self._dirty = True

        elif event_type == EventType.TOOL_RESULT:
            tool = event.data.get("tool_name", "unknown")
            elapsed_ms = 0
            if tool in self._tool_starts:
                elapsed_ms = int((time.monotonic() - self._tool_starts.pop(tool)) * 1000)
            timing = f" {elapsed_ms}ms" if elapsed_ms > 0 else ""
            self._lines.append(Text(f"  \u2713{timing}", style="dim green"))
            self._dirty = True

        elif event_type == EventType.DELTA:
            content = event.data.get("content", "")
            if content:
                self._text_buffer += content
                while "\n" in self._text_buffer:
                    line, self._text_buffer = self._text_buffer.split("\n", 1)
                    self._lines.append(Text(line))
                self._dirty = True

        elif event_type == EventType.ERROR:
            self._flush_text()
            msg = event.data.get("message", "Unknown error")
            self._lines.append(Text(f"  Error: {msg}", style="bold red"))
            self._dirty = True

        elif event_type == EventType.COMPLETE:
            self._flush_text()
            self._dirty = True

    def render_tick(self) -> None:
        """Throttled refresh."""
        if self._live is None or not self._dirty:
            return
        now = time.monotonic()
        if now - self._last_refresh < self._REFRESH_MIN_INTERVAL:
            return
        self._last_refresh = now
        self._dirty = False
        self._live.update(self._build_renderable(), refresh=True)

    def finalize(self) -> None:
        """Print accumulated content to scrollback after Live stops."""
        self._flush_text()
        for line in self._lines:
            self._console.print(line)
        self._lines.clear()
        self._console.print()  # blank separator

    # ---- 内部 ----

    def _flush_text(self) -> None:
        if self._text_buffer:
            self._lines.append(Text(self._text_buffer))
            self._text_buffer = ""

    def _build_renderable(self) -> Any:
        from rich.console import Group

        self._flush_text()

        # Content preview: always _MAX_PREVIEW_LINES rows
        preview = list(self._lines[-(_MAX_PREVIEW_LINES):]) if self._lines else []
        while len(preview) < _MAX_PREVIEW_LINES:
            preview.append(Text(""))

        # Toolbar
        status = self._status_provider() if self._status_provider else None
        if status is not None:
            from mindbot.cli.shell.toolbar import render_status_line
            toolbar = render_status_line(status, self._columns)
        else:
            toolbar = Text("")

        return Group(
            *preview,
            Text("\u2500" * self._columns, style="dim"),
            toolbar,
        )
