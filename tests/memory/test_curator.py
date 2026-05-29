from __future__ import annotations

from mindbot.context.models import Message, ToolCall
from mindbot.memory.curator import MemoryCurator


def test_curator_ignores_plain_qa_turn() -> None:
    curator = MemoryCurator()

    result = curator.curate_turn(user_text="你好", assistant_text="你好，有什么可以帮你？")

    assert result == []


def test_curator_extracts_preference() -> None:
    curator = MemoryCurator()

    result = curator.curate_turn(
        user_text="我喜欢用深色主题",
        assistant_text="记住了",
    )

    assert len(result) == 1
    assert result[0].kind == "preference"
    assert result[0].content == "我喜欢用深色主题"


def test_curator_extracts_side_effect_tool_result() -> None:
    curator = MemoryCurator()
    trace = [
        Message(
            role="assistant",
            content="I will update it.",
            tool_calls=[
                ToolCall(id="tc1", name="write_file", arguments={"path": "README.md"}),
            ],
        ),
        Message(role="tool", content="ok", tool_call_id="tc1", tool_name="write_file"),
    ]

    result = curator.curate_turn(
        user_text="更新 README",
        assistant_text="已更新 README",
        trace=trace,
    )

    assert result
    assert result[0].kind == "project_note"
