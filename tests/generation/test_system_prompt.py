from __future__ import annotations

from mindbot.generation.system_prompt_builder import build_system_prompt


def test_build_system_prompt_lists_tools_and_dynamic_guidance() -> None:
    prompt = build_system_prompt(
        base_prompt="你是测试助手。",
        tool_names=["read_file", "create_tool", "exec_command"],
    )

    assert "你是测试助手。" in prompt
    assert "`read_file`" in prompt
    assert "`create_tool`" in prompt
    assert "动态工具创建" in prompt


def test_build_system_prompt_handles_empty_tools() -> None:
    prompt = build_system_prompt()
    assert "当前未挂载任何工具" in prompt
