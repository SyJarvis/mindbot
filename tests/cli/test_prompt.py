"""ShellPrompt 单元测试。"""

from __future__ import annotations

from mindbot.cli.shell.prompt import ShellPrompt
from mindbot.cli.shell.toolbar import StatusSnapshot


def _make_status() -> StatusSnapshot:
    return StatusSnapshot(
        model_name="test-model",
        workspace="/tmp",
        session_id="test",
    )


def _make_prompt() -> ShellPrompt:
    return ShellPrompt(
        status_provider=lambda: _make_status(),
        slash_commands=None,
    )


def test_prompt_creates_successfully():
    prompt = _make_prompt()
    assert prompt is not None
    assert prompt._session is not None


def test_prompt_render_message_fixed_height():
    """message 回调固定返回分隔线 + > 提示符。"""
    prompt = _make_prompt()
    result = prompt._render_message()
    assert isinstance(result, list)
    all_text = "".join(frag[1] for frag in result)
    assert ">" in all_text
    assert "\u2500" in all_text  # separator ─


def test_prompt_render_toolbar():
    prompt = _make_prompt()
    result = prompt._render_toolbar()
    assert isinstance(result, list)
    all_text = "".join(frag[1] for frag in result)
    assert "test-model" in all_text
