"""Tests for interactive shell rendering helpers."""

from __future__ import annotations

from mindbot.agent.models import AgentEvent
from mindbot.cli import _ShellEventState, _emit_shell_event, _render_shell_response, console


def test_emit_shell_event_renders_delta_and_tool_updates():
    state = _ShellEventState()

    with console.capture() as capture:
        _emit_shell_event(AgentEvent.delta("Hello"), state)
        _emit_shell_event(AgentEvent.tool_executing("search", "call-1"), state)

    output = capture.get()
    assert "Hello" in output
    assert "Running tool: search" in output
    assert state.saw_delta is True


def test_render_shell_response_prints_when_no_delta_seen():
    state = _ShellEventState()

    with console.capture() as capture:
        _render_shell_response("Final answer", state)

    output = capture.get()
    assert "Final answer" in output


def test_render_shell_response_skips_duplicate_when_delta_already_rendered():
    state = _ShellEventState(saw_delta=True, line_open=True)

    with console.capture() as capture:
        _render_shell_response("Already streamed", state)

    output = capture.get()
    assert "Already streamed" not in output
