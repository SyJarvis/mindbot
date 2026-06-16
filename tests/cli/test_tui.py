import asyncio

from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document
import pytest

from mindbot.agent.models import AgentEvent, RuntimeRequest
from mindbot.cli.shell import Shell
from mindbot.cli.shell import _TuiTextState, _handle_tui_event
from mindbot.cli.shell.tui import (
    TuiApp,
    _SlashCompleter,
    _TuiMessages,
    _selection_bounds_for_line,
    _slice_by_cells,
    _wrap_terminal_line,
)


def test_tui_messages_render_multiline_user_input() -> None:
    messages = _TuiMessages()

    messages.append_user_input("first line\nsecond line")

    fragments = list(messages.render())
    rendered = "".join(text for _style, text in fragments)

    assert " > first line" in rendered
    assert "   second line" in rendered


def test_tui_user_input_keeps_composer_background_width() -> None:
    messages = _TuiMessages()

    messages.append_user_input("hi")

    visual = messages.visual_lines(8)

    assert visual.count(("class:user-input", "        ")) == 2
    assert ("class:user-input", " > hi   ") in visual


def test_tui_turn_summary_replaces_work_status_with_worked_line() -> None:
    messages = _TuiMessages()
    messages.append_thinking()

    from mindbot.cli.shell.toolbar import StatusSnapshot

    app = TuiApp(
        status_provider=lambda: StatusSnapshot(model_name="m", workspace=".", session_id="s"),
        on_submit=lambda text: None,
    )
    app._messages = messages

    app.add_turn_summary(1.2, 3, 4)

    fragments = list(messages.render())

    assert ("class:work-status", "  working...") not in fragments
    assert ("class:dim", "  worked · 1.2s · 3 tokens · context 4%") in fragments


def test_tui_tool_result_updates_tool_line() -> None:
    messages = _TuiMessages()

    messages.append_tool_start("shell", "ls")
    messages.append_tool_result(12)

    fragments = list(messages.render())

    assert ("class:tool", "  ⏺ shell  ls") not in fragments
    assert ("class:tool-ok", "  ⏺ shell  ls  ✓ 12ms") in fragments


def test_tui_plain_text_for_copy() -> None:
    messages = _TuiMessages()

    messages.append_user_input("hello")
    messages.append("world")

    assert "hello" in messages.plain_text()
    assert messages.plain_text().endswith("world")


def test_tui_selection_helpers_slice_by_terminal_cells() -> None:
    assert _slice_by_cells("hello", 1, 4) == "ell"
    assert _selection_bounds_for_line(((1, 2), (1, 4)), 1, "hello") == (2, 4)


def test_tui_selected_text_uses_visible_lines() -> None:
    from mindbot.cli.shell.toolbar import StatusSnapshot

    app = TuiApp(
        status_provider=lambda: StatusSnapshot(model_name="m", workspace=".", session_id="s"),
        on_submit=lambda text: None,
    )
    app._messages.append("hello")
    app._messages.append("world")
    app._selection_range = ((0, 1), (1, 3))

    assert app._selected_text() == "ello\nwor"


def test_tui_scroll_disables_auto_follow_until_bottom() -> None:
    from mindbot.cli.shell.toolbar import StatusSnapshot

    app = TuiApp(
        status_provider=lambda: StatusSnapshot(model_name="m", workspace=".", session_id="s"),
        on_submit=lambda text: None,
    )
    for i in range(40):
        app._messages.append(f"line {i}")
    app._invalidate()

    app._scroll_by(-3)

    assert app._auto_follow is False


def test_tui_messages_upsert_and_finalize_delta() -> None:
    messages = _TuiMessages()

    messages.upsert_delta("hel")
    messages.upsert_delta("hello")
    messages.finalize_delta()

    fragments = list(messages.render())

    assert ("", "hello") in fragments
    assert ("class:streaming", "hello") not in fragments


def test_tui_messages_complete_stream_line_replaces_partial() -> None:
    messages = _TuiMessages()

    messages.upsert_delta("hello")
    messages.append_stream_line("hello world")

    fragments = list(messages.render())

    assert ("", "hello") not in fragments
    assert ("", "hello world") in fragments


def test_tui_messages_wrap_visual_lines_for_scrolling() -> None:
    messages = _TuiMessages()

    messages.append("abcdefghi")

    assert messages.visual_line_count(8) == 2
    assert list(messages.render_view(8, 1, 1)) == [("", "i"), ("", "\n")]


def test_slash_completer_keeps_slash_prefix() -> None:
    completer = _SlashCompleter(["help", "status"])

    completions = list(completer.get_completions(Document("/he"), CompleteEvent()))

    assert completions
    assert completions[0].text == "help"
    assert completions[0].start_position == -2


def test_wrap_terminal_line_preserves_empty_line() -> None:
    assert _wrap_terminal_line("", 10) == [""]


def test_tui_event_handler_accepts_cumulative_delta() -> None:
    messages = _TuiMessages()

    class FakeTui:
        def add_line(self, text: str) -> None:
            messages.append(text)

        def add_stream_line(self, text: str) -> None:
            messages.append_stream_line(text)

        def upsert_delta(self, text: str) -> None:
            messages.upsert_delta(text)

        def finalize_delta(self) -> None:
            messages.finalize_delta()

    state: object = _TuiTextState()
    state, _ = _handle_tui_event(FakeTui(), AgentEvent.delta("hello"), {}, state)
    state, _ = _handle_tui_event(FakeTui(), AgentEvent.delta("hello world"), {}, state)

    fragments = list(messages.render())

    assert ("class:streaming", "hello world") in fragments


def test_tui_event_handler_replaces_partial_when_line_completes() -> None:
    messages = _TuiMessages()

    class FakeTui:
        def add_stream_line(self, text: str) -> None:
            messages.append_stream_line(text)

        def upsert_delta(self, text: str) -> None:
            messages.upsert_delta(text)

        def finalize_delta(self) -> None:
            messages.finalize_delta()

    state: object = _TuiTextState()
    state, _ = _handle_tui_event(FakeTui(), AgentEvent.delta("hello"), {}, state)
    state, _ = _handle_tui_event(FakeTui(), AgentEvent.delta(" world\n"), {}, state)

    fragments = list(messages.render())

    assert ("class:streaming", "hello") not in fragments
    assert ("", "hello world") in fragments


def test_tui_work_status_stays_below_streaming_text() -> None:
    messages = _TuiMessages()

    messages.append_thinking()
    messages.upsert_delta("hello")

    fragments = list(messages.render())

    assert fragments.index(("class:streaming", "hello")) < fragments.index(("class:work-status", "  working..."))


@pytest.mark.anyio
async def test_shell_submit_resolves_pending_user_input_request() -> None:
    class FakeTui:
        def __init__(self) -> None:
            self.user_inputs: list[str] = []

        def exit(self) -> None:
            pass

        def add_user_input(self, text: str) -> None:
            self.user_inputs.append(text)

    shell = Shell(bot=None, config_file=None)
    shell._tui = FakeTui()
    future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
    shell._runtime._pending_runtime_answer = future
    shell._runtime._pending_runtime_request = RuntimeRequest.user_input(
        request_id="req-1",
        prompt="Continue?",
    )

    await shell._on_tui_submit("continue")

    assert future.result() == "continue"
    assert shell._runtime.pending_user_input_request_id is None
    assert shell._tui.user_inputs == ["continue"]


@pytest.mark.anyio
async def test_shell_submit_queues_input_during_running_turn() -> None:
    class FakeTui:
        def __init__(self) -> None:
            self.user_inputs: list[str] = []

        def add_user_input(self, text: str) -> None:
            self.user_inputs.append(text)

    async def wait_forever() -> None:
        await asyncio.Event().wait()

    shell = Shell(bot=None, config_file=None)
    shell._tui = FakeTui()
    shell._runtime._turn_task = asyncio.create_task(wait_forever())

    try:
        await shell._on_tui_submit("also check humidity")

        assert shell._runtime.drain_queued_user_inputs_now() == ["also check humidity"]
        assert shell._tui.user_inputs == ["also check humidity"]
    finally:
        shell._runtime._turn_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await shell._runtime._turn_task


@pytest.mark.anyio
async def test_shell_drains_queued_input_for_active_turn() -> None:
    shell = Shell(bot=None, config_file=None)
    shell._runtime._queued_user_inputs = ["first", "second"]

    drained = shell._runtime.drain_queued_user_inputs_now()

    assert drained == ["first", "second"]
    assert shell._runtime.queued_count == 0
