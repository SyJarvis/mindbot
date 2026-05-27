"""全屏 TUI Shell — Codex-style interactive layout.

Layout: transcript (scrollable) + composer (fixed) + status bar (fixed).

使用 prompt_toolkit Application 直接构造，不再依赖 PromptSession。
"""

from __future__ import annotations

import asyncio
import base64
import os
import time
from typing import Any, Callable

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Float, FloatContainer, HSplit, Layout, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.margins import Margin
from prompt_toolkit.layout.processors import BeforeInput, HighlightMatchingBracketProcessor
from prompt_toolkit.mouse_events import MouseButton, MouseEventType
from prompt_toolkit.styles import Style as PTKStyle
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.utils import get_cwidth

from mindbot.cli.shell.toolbar import StatusSnapshot, render_toolbar


# ── Base TUI Shell ──────────────────────────────────────────────────────────

class _TuiMessages:
    """Append-only transcript displayed in the scrollable area."""

    _WORK_STATUS_STYLE = "class:work-status"

    def __init__(self) -> None:
        self._lines: list[tuple[str, str]] = []  # (style_name, text)

    def append(self, text: str, style: str = "", *, preserve_work_status: bool = True) -> None:
        status = self._pop_work_status() if preserve_work_status else None
        self._lines.append((style, text))
        self._restore_work_status(status)

    def append_stream_line(self, text: str, style: str = "") -> None:
        status = self._pop_work_status()
        if self._lines and self._lines[-1][0] == "class:streaming":
            self._lines[-1] = (style, text)
        else:
            self._lines.append((style, text))
        self._restore_work_status(status)

    def upsert_delta(self, text: str) -> None:
        """Replace last delta-text line, or start a new one."""
        status = self._pop_work_status()
        if self._lines and self._lines[-1][0] == "class:streaming":
            self._lines[-1] = ("class:streaming", text)
        else:
            self._lines.append(("class:streaming", text))
        self._restore_work_status(status)

    def finalize_delta(self) -> None:
        """Convert the last streaming delta into a normal line."""
        status = self._pop_work_status()
        if self._lines and self._lines[-1][0] == "class:streaming":
            self._lines[-1] = ("", self._lines[-1][1])
        self._restore_work_status(status)

    def append_thinking(self) -> None:
        self.set_work_status("  working...")

    def set_work_status(self, text: str) -> None:
        self._pop_work_status()
        self._lines.append((self._WORK_STATUS_STYLE, text))

    def clear_work_status(self) -> None:
        self._pop_work_status()

    def append_user_input(self, text: str) -> None:
        self.append("", "", preserve_work_status=False)
        self.append("", "class:user-input", preserve_work_status=False)
        for i, line in enumerate(text.splitlines() or [""]):
            prefix = "> " if i == 0 else "  "
            self.append(f" {prefix}{line}", "class:user-input", preserve_work_status=False)
        self.append("", "class:user-input", preserve_work_status=False)
        self.append("", "", preserve_work_status=False)

    def append_tool_start(self, tool: str, args_hint: str) -> None:
        label = f"  ⏺ {tool}"
        if args_hint:
            label += f"  {args_hint}"
        self.append(label, "class:tool")

    def append_tool_result(self, elapsed_ms: int) -> None:
        timing = f" {elapsed_ms}ms" if elapsed_ms > 0 else ""
        status = self._pop_work_status()
        if self._lines and self._lines[-1][0] == "class:tool":
            self._lines[-1] = ("class:tool-ok", f"{self._lines[-1][1]}  ✓{timing}")
        else:
            self._lines.append(("class:tool-ok", f"  ✓{timing}"))
        self._restore_work_status(status)

    def append_error(self, msg: str) -> None:
        self.append(f"  ✗ {msg}", "class:error")

    def append_interrupted(self) -> None:
        self.append("  interrupted", "class:interrupted")

    def render(self) -> FormattedText:
        return FormattedText(self._render_fragments(self._lines))

    def plain_text(self) -> str:
        return "\n".join(text for _style, text in self._lines).rstrip()

    def render_view(
        self,
        columns: int,
        height: int,
        top: int,
        selection: tuple[tuple[int, int], tuple[int, int]] | None = None,
    ) -> FormattedText:
        visual_lines = self.visual_lines(columns)
        visible = visual_lines[top:top + height]
        return FormattedText(self._render_fragments(visible, top=top, selection=selection))

    def visual_line_count(self, columns: int) -> int:
        return len(self.visual_lines(columns))

    def visual_lines(self, columns: int) -> list[tuple[str, str]]:
        width = max(8, columns)
        visual: list[tuple[str, str]] = []
        for style, text in self._lines:
            for line in _wrap_terminal_line(text, width):
                if style == "class:user-input":
                    line = _pad_terminal_line(line, width)
                visual.append((style, line))
        return visual

    def _render_fragments(
        self,
        lines: list[tuple[str, str]],
        *,
        top: int = 0,
        selection: tuple[tuple[int, int], tuple[int, int]] | None = None,
    ) -> list[tuple[str, str]]:
        fragments: list[tuple[str, str]] = []
        for offset, (style, text) in enumerate(lines):
            selected = _selection_bounds_for_line(selection, top + offset, text)
            if selected is None:
                fragments.append((style, text))
            else:
                start, end = selected
                before, selected_text, after = _split_by_cells(text, start, end)
                if before:
                    fragments.append((style, before))
                if selected_text:
                    fragments.append(("class:selection", selected_text))
                if after:
                    fragments.append((style, after))
            fragments.append(("", "\n"))
        return fragments

    @property
    def line_count(self) -> int:
        return len(self._lines)

    def _pop_work_status(self) -> tuple[str, str] | None:
        if self._lines and self._lines[-1][0] == self._WORK_STATUS_STYLE:
            return self._lines.pop()
        return None

    def _restore_work_status(self, status: tuple[str, str] | None) -> None:
        if status is not None:
            self._lines.append(status)


class _StatusBar:
    """Re-renderable status bar using the existing toolbar renderer."""

    def __init__(self, status_provider: Callable[[], StatusSnapshot]) -> None:
        self._provider = status_provider

    def render(self, columns: int) -> FormattedText:
        status = self._provider()
        return _without_first_line(render_toolbar(status, max(40, columns)))


class _TranscriptControl(FormattedTextControl):
    def __init__(self, tui: "TuiApp") -> None:
        self._tui = tui
        super().__init__(
            text=lambda: tui._messages.render_view(
                tui._transcript_columns(),
                tui._transcript_height(),
                tui._scroll_offset,
                tui._selection_range,
            ),
            focusable=False,
        )

    def mouse_handler(self, mouse_event: Any) -> Any:
        if mouse_event.event_type == MouseEventType.SCROLL_UP:
            self._tui._scroll_by(-3)
            return None
        if mouse_event.event_type == MouseEventType.SCROLL_DOWN:
            self._tui._scroll_by(3)
            return None
        if mouse_event.button == MouseButton.LEFT:
            if mouse_event.event_type == MouseEventType.MOUSE_DOWN:
                self._tui._start_selection(mouse_event.position.y, mouse_event.position.x)
                return None
            if mouse_event.event_type == MouseEventType.MOUSE_MOVE:
                self._tui._update_selection(mouse_event.position.y, mouse_event.position.x)
                return None
            if mouse_event.event_type == MouseEventType.MOUSE_UP:
                self._tui._finish_selection(mouse_event.position.y, mouse_event.position.x)
                return None
        return super().mouse_handler(mouse_event)


class _TranscriptScrollbar(Margin):
    def __init__(self, tui: "TuiApp") -> None:
        self._tui = tui

    def get_width(self, get_ui_content: Any) -> int:
        return 1

    def create_margin(self, window_render_info: Any, width: int, height: int) -> list[tuple[str, str]]:
        total = self._tui._messages.visual_line_count(self._tui._transcript_columns())
        visible = self._tui._transcript_height()
        if total <= visible:
            return [("class:scrollbar.background", " \n") for _ in range(height)]

        thumb_height = max(1, int(height * visible / total))
        max_top = max(0, height - thumb_height)
        bottom = self._tui._bottom_scroll_offset()
        thumb_top = 0 if bottom == 0 else int(max_top * self._tui._scroll_offset / bottom)

        fragments: list[tuple[str, str]] = []
        for row in range(height):
            style = "class:scrollbar.button" if thumb_top <= row < thumb_top + thumb_height else "class:scrollbar.background"
            fragments.append((style, " "))
            fragments.append(("", "\n"))
        return fragments


class TuiApp:
    """Encapsulates the prompt_toolkit Application and its layout.

    Usage::

        app = TuiApp(status_provider=...)
        await app.run()
    """

    def __init__(
        self,
        *,
        status_provider: Callable[[], StatusSnapshot],
        on_submit: Callable[[str], Any],
        slash_commands: list[str] | None = None,
    ) -> None:
        self._status_bar = _StatusBar(status_provider)
        self._messages = _TuiMessages()
        self._on_submit = on_submit
        self._slash_commands = slash_commands or []

        self._input_buffer = Buffer(
            multiline=True,
            completer=_SlashCompleter(self._slash_commands) if self._slash_commands else None,
            complete_while_typing=True,
        )
        self._interrupted = False
        self._exit_requested = False
        self._scroll_offset = 0
        self._auto_follow = True
        self._selection_anchor: tuple[int, int] | None = None
        self._selection_range: tuple[tuple[int, int], tuple[int, int]] | None = None
        self._copy_notice_until = 0.0
        self._application = self._build_application()

    # ── Public API ─────────────────────────────────────────────────────────

    def add_line(self, text: str, style: str = "") -> None:
        self._messages.append(text, style)
        self._invalidate()

    def add_stream_line(self, text: str, style: str = "") -> None:
        self._messages.append_stream_line(text, style)
        self._invalidate()

    def add_welcome(self, lines: list[tuple[str, str]]) -> None:
        """Prepend welcome / startup lines before any conversation."""
        try:
            cols = os.get_terminal_size().columns
        except OSError:
            cols = 60
        bw = min(cols, 62)
        self._messages.append("╭" + "─" * (bw - 2) + "╮", "class:welcome-border")
        for text, style in lines:
            line = "│ " + text
            right_pad = bw - len(line) - 1
            if right_pad > 0:
                line += " " * right_pad
            line += "│"
            self._messages.append(line, style)
        self._messages.append("╰" + "─" * (bw - 2) + "╯", "class:welcome-border")
        self._messages.append("", "")

    def upsert_delta(self, text: str) -> None:
        """Update streaming delta line (replaces previous partial line)."""
        self._messages.upsert_delta(text)
        self._invalidate()

    def finalize_delta(self) -> None:
        self._messages.finalize_delta()
        self._invalidate()

    def add_user_input(self, text: str) -> None:
        self._auto_follow = True
        self._messages.append_user_input(text)
        self._invalidate()

    def add_thinking(self) -> None:
        self._messages.append_thinking()
        self._invalidate()

    def set_work_status(self, text: str) -> None:
        self._messages.set_work_status(text)
        self._invalidate()

    def clear_work_status(self) -> None:
        self._messages.clear_work_status()
        self._invalidate()

    def add_tool_start(self, tool: str, args_hint: str) -> None:
        self._messages.append_tool_start(tool, args_hint)
        self._invalidate()

    def add_tool_result(self, elapsed_ms: int) -> None:
        self._messages.append_tool_result(elapsed_ms)
        self._invalidate()

    def add_error(self, msg: str) -> None:
        self._messages.append_error(msg)
        self._invalidate()

    def add_interrupted(self) -> None:
        self._messages.append_interrupted()
        self._invalidate()

    def add_turn_summary(self, elapsed_sec: float, tokens_used: int, context_pct: float) -> None:
        self._messages.clear_work_status()
        parts = ["worked", f"{elapsed_sec:.1f}s"]
        if tokens_used > 0:
            parts.append(f"{tokens_used:,} tokens")
        if context_pct > 0:
            parts.append(f"context {context_pct:.0f}%")
        sep = " · "
        self._messages.append(f"  {sep.join(parts)}", "class:dim", preserve_work_status=False)
        self._messages.append("", "", preserve_work_status=False)
        self._invalidate()

    def clear_input(self) -> None:
        self._input_buffer.text = ""

    def copy_transcript(self) -> None:
        text = self._messages.plain_text()
        self._copy_text(text)

    def _copy_text(self, text: str) -> None:
        self._application.clipboard.set_text(text)
        if self._application.is_running:
            _copy_to_terminal_clipboard(self._application.output, text)
            self._show_copy_notice()

    async def run(self) -> None:
        await self._application.run_async()

    def exit(self) -> None:
        self._exit_requested = True
        if self._application.is_running:
            self._application.exit()

    @property
    def interrupted(self) -> bool:
        return self._interrupted

    def reset_interrupted(self) -> None:
        self._interrupted = False

    # ── Internal ───────────────────────────────────────────────────────────

    def _invalidate(self) -> None:
        if self._auto_follow:
            self._scroll_offset = self._bottom_scroll_offset()
        if self._application.is_running:
            self._application.invalidate()

    def _build_application(self) -> "Application[Any]":
        kb = self._build_key_bindings()

        # ── Layout ──────────────────────────────────────────────────────
        # message area (scrollable)
        message_window = Window(
            content=_TranscriptControl(self),
            always_hide_cursor=True,
            wrap_lines=False,
            right_margins=[_TranscriptScrollbar(self)],
        )

        transcript_gap = Window(
            height=1,
            char=" ",
            style="class:transcript-gap",
        )

        composer_top = Window(
            height=1,
            char=" ",
            style="class:composer",
        )

        input_window = Window(
            content=BufferControl(
                buffer=self._input_buffer,
                input_processors=[BeforeInput("> "), HighlightMatchingBracketProcessor()],
            ),
            height=1,
            style="class:composer",
            char=" ",
            wrap_lines=False,
        )

        composer_bottom = Window(
            height=1,
            char=" ",
            style="class:composer",
        )

        status_window = Window(
            content=FormattedTextControl(
                text=lambda: self._render_status(),
                focusable=False,
            ),
            height=2,
            always_hide_cursor=True,
        )

        root = HSplit([
            message_window,
            transcript_gap,
            composer_top,
            input_window,
            composer_bottom,
            status_window,
        ])

        container = FloatContainer(
            content=root,
            floats=[
                Float(
                    content=Window(
                        content=FormattedTextControl(
                            text=lambda: self._render_copy_notice(),
                            focusable=False,
                        ),
                        height=1,
                        width=12,
                        style="class:copy-notice",
                        always_hide_cursor=True,
                    ),
                    top=0,
                    right=2,
                ),
            ],
        )

        layout = Layout(container)

        # ── Style ───────────────────────────────────────────────────────
        style = PTKStyle.from_dict({
            "welcome-title": "bold #56d4e6",
            "welcome-dim": "fg:#7c8594",
            "welcome-border": "fg:#3a3f4b",
            "transcript-gap": "",
            "composer": "bg:#20242c fg:#d4d4d4",
            "scrollbar.background": "bg:#20242c",
            "scrollbar.button": "bg:#626b7a",
            "input.separator": "fg:#3a3f4b",
            "input.label": "fg:#7c8594",
            "user-input": "bg:#20242c fg:#d4d4d4",
            "thinking": "fg:#7c8594 italic",
            "work-status": "fg:#7c8594 italic",
            "streaming": "fg:#d4d4d4",
            "selection": "bg:#3a6070 fg:#ffffff",
            "copy-notice": "bg:#20242c fg:#56d364 bold",
            "tool": "fg:#c9a646",
            "tool-ok": "fg:#56d364",
            "error": "bold #ff7b72",
            "interrupted": "fg:#f2cc60",
            "dim": "fg:#7c8594",
            "toolbar.model": "#56d4e6 bold",
            "toolbar.cwd": "fg:#7c8594",
            "toolbar.tip": "fg:#626b7a",
            "toolbar.thinking": "fg:#56d4e6",
            "toolbar.idle": "fg:#626b7a",
            "toolbar.context": "fg:#626b7a",
            "toolbar.toast": "fg:#7c8594",
        })

        return Application(
            layout=layout,
            key_bindings=kb,
            style=style,
            full_screen=True,
            mouse_support=True,
        )

    def _render_status(self) -> FormattedText:
        return self._status_bar.render(self._terminal_columns())

    def _bottom_scroll_offset(self) -> int:
        return max(
            0,
            self._messages.visual_line_count(self._transcript_columns()) - self._transcript_height(),
        )

    def _scroll_by(self, lines: int) -> None:
        self._scroll_offset = min(
            self._bottom_scroll_offset(),
            max(0, self._scroll_offset + lines),
        )
        self._auto_follow = self._scroll_offset >= self._bottom_scroll_offset()
        if self._application.is_running:
            self._application.invalidate()

    def _start_selection(self, row: int, col: int) -> None:
        point = (self._scroll_offset + max(0, row), max(0, col))
        self._selection_anchor = point
        self._selection_range = (point, point)
        if self._application.is_running:
            self._application.invalidate()

    def _update_selection(self, row: int, col: int) -> None:
        if self._selection_anchor is None:
            return
        point = (self._scroll_offset + max(0, row), max(0, col))
        self._selection_range = (self._selection_anchor, point)
        if self._application.is_running:
            self._application.invalidate()

    def _finish_selection(self, row: int, col: int) -> None:
        if self._selection_anchor is None:
            return
        point = (self._scroll_offset + max(0, row), max(0, col))
        self._selection_range = (self._selection_anchor, point)
        text = self._selected_text()
        if text:
            self._copy_text(text)
        self._selection_anchor = None
        if self._application.is_running:
            self._application.invalidate()

    def _selected_text(self) -> str:
        if self._selection_range is None:
            return ""
        visual_lines = [text for _style, text in self._messages.visual_lines(self._transcript_columns())]
        (start_row, start_col), (end_row, end_col) = _normalize_selection(self._selection_range)
        if not visual_lines or start_row >= len(visual_lines):
            return ""
        selected: list[str] = []
        for row in range(start_row, min(end_row, len(visual_lines) - 1) + 1):
            line = visual_lines[row]
            left = start_col if row == start_row else 0
            right = end_col if row == end_row else _terminal_width(line)
            selected.append(_slice_by_cells(line, left, right).rstrip())
        return "\n".join(selected).strip()

    def _show_copy_notice(self) -> None:
        self._copy_notice_until = time.monotonic() + 1.4
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.call_later(1.4, self._expire_copy_notice)
        self._application.invalidate()

    def _expire_copy_notice(self) -> None:
        if self._application.is_running:
            self._application.invalidate()

    def _render_copy_notice(self) -> FormattedText:
        if time.monotonic() <= self._copy_notice_until:
            return FormattedText([("class:copy-notice", " copied ")])
        return FormattedText([])

    def _transcript_height(self) -> int:
        try:
            rows = os.get_terminal_size().lines
        except OSError:
            rows = 24
        return max(1, rows - 6)  # 1-line gap + 3-line composer + 2-line status bar

    def _transcript_columns(self) -> int:
        return max(8, self._terminal_columns() - 1)  # reserve right scrollbar margin

    def _terminal_columns(self) -> int:
        try:
            size = os.get_terminal_size()
            return size.columns
        except OSError:
            return 80

    def _build_key_bindings(self) -> KeyBindings:
        kb = KeyBindings()
        input_empty = Condition(lambda: not self._input_buffer.text)

        @kb.add("enter", eager=True)
        def _submit(event: Any) -> None:
            text = self._input_buffer.text.strip()
            if text:
                self._input_buffer.text = ""
                asyncio.ensure_future(self._on_submit(text))

        @kb.add("c-c", eager=True)
        def _interrupt(event: Any) -> None:
            self._interrupted = True

        @kb.add("c-d", eager=True)
        def _exit(event: Any) -> None:
            self._exit_requested = True
            event.app.exit()

        @kb.add("c-y", eager=True)
        def _copy_transcript(event: Any) -> None:
            self.copy_transcript()

        @kb.add("escape", "enter", eager=True)
        def _newline(event: Any) -> None:
            self._input_buffer.insert_text("\n")

        @kb.add("pageup", eager=True)
        def _page_up(event: Any) -> None:
            self._scroll_by(-10)

        @kb.add("pagedown", eager=True)
        def _page_down(event: Any) -> None:
            self._scroll_by(10)

        @kb.add("escape", "up", eager=True)
        def _alt_up(event: Any) -> None:
            self._scroll_by(-3)

        @kb.add("escape", "down", eager=True)
        def _alt_down(event: Any) -> None:
            self._scroll_by(3)

        @kb.add("up", filter=input_empty, eager=True)
        def _up(event: Any) -> None:
            self._scroll_by(-1)

        @kb.add("down", filter=input_empty, eager=True)
        def _down(event: Any) -> None:
            self._scroll_by(1)

        @kb.add("left", filter=input_empty, eager=True)
        def _left(event: Any) -> None:
            self._scroll_by(-10)

        @kb.add("right", filter=input_empty, eager=True)
        def _right(event: Any) -> None:
            self._scroll_by(10)

        return kb


# ── Slash Completer ─────────────────────────────────────────────────────────

class _SlashCompleter(Completer):
    def __init__(self, commands: list[str]) -> None:
        self._commands = commands

    def get_completions(self, document: Any, complete_event: Any):
        text = document.text_before_cursor
        if text.startswith("/"):
            prefix = text[1:]
            for cmd in self._commands:
                if cmd.startswith(prefix):
                    yield Completion(cmd, start_position=-len(prefix))


def _without_first_line(text: FormattedText) -> FormattedText:
    """Drop the input-border row from the shared toolbar renderer."""
    fragments: list[tuple[str, str]] = []
    skipping = True
    for style, value in text:
        if not skipping:
            fragments.append((style, value))
            continue
        if "\n" not in value:
            continue
        _before, after = value.split("\n", 1)
        skipping = False
        if after:
            fragments.append((style, after))
    return FormattedText(fragments)


def _wrap_terminal_line(text: str, columns: int) -> list[str]:
    if text == "":
        return [""]

    lines: list[str] = []
    current: list[str] = []
    width = 0
    for ch in text:
        ch_width = max(0, get_cwidth(ch))
        if current and width + ch_width > columns:
            lines.append("".join(current))
            current = []
            width = 0
        current.append(ch)
        width += ch_width
    lines.append("".join(current))
    return lines


def _pad_terminal_line(text: str, columns: int) -> str:
    return text + " " * max(0, columns - _terminal_width(text))


def _terminal_width(text: str) -> int:
    return sum(max(0, get_cwidth(ch)) for ch in text)


def _normalize_selection(
    selection: tuple[tuple[int, int], tuple[int, int]],
) -> tuple[tuple[int, int], tuple[int, int]]:
    start, end = selection
    if start > end:
        return end, start
    return start, end


def _selection_bounds_for_line(
    selection: tuple[tuple[int, int], tuple[int, int]] | None,
    row: int,
    text: str,
) -> tuple[int, int] | None:
    if selection is None:
        return None
    (start_row, start_col), (end_row, end_col) = _normalize_selection(selection)
    if row < start_row or row > end_row:
        return None
    left = start_col if row == start_row else 0
    right = end_col if row == end_row else _terminal_width(text)
    if right < left:
        left, right = right, left
    if right == left:
        right += 1
    return max(0, left), max(0, right)


def _split_by_cells(text: str, start: int, end: int) -> tuple[str, str, str]:
    return (
        _slice_by_cells(text, 0, start),
        _slice_by_cells(text, start, end),
        _slice_by_cells(text, end, _terminal_width(text)),
    )


def _slice_by_cells(text: str, start: int, end: int) -> str:
    if end <= start:
        return ""
    chars: list[str] = []
    pos = 0
    for ch in text:
        width = max(0, get_cwidth(ch))
        next_pos = pos + width
        if next_pos > start and pos < end:
            chars.append(ch)
        pos = next_pos
    return "".join(chars)


def _copy_to_terminal_clipboard(output: Any, text: str) -> None:
    payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
    output.write_raw(f"\x1b]52;c;{payload}\x07")
    output.flush()
