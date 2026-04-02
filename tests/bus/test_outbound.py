from __future__ import annotations

from mindbot.agent.models import AgentResponse
from mindbot.bus import OUTBOUND_MESSAGE_METADATA_KEY, build_outbound_message


def test_build_outbound_message_defaults_to_agent_content():
    response = AgentResponse(content="hello")

    message = build_outbound_message(
        channel="feishu",
        chat_id="oc_test",
        response=response,
    )

    assert message.channel == "feishu"
    assert message.chat_id == "oc_test"
    assert message.content == "hello"
    assert message.media == []
    assert message.reply_to is None
    assert message.metadata == {}


def test_build_outbound_message_uses_structured_attachment_metadata():
    response = AgentResponse(
        content="fallback",
        metadata={
            OUTBOUND_MESSAGE_METADATA_KEY: {
                "content": "caption",
                "media": ["/tmp/report.pdf"],
                "reply_to": "msg_123",
                "metadata": {"source": "tool"},
            }
        },
    )

    message = build_outbound_message(
        channel="feishu",
        chat_id="oc_test",
        response=response,
    )

    assert message.content == "caption"
    assert message.media == ["/tmp/report.pdf"]
    assert message.reply_to == "msg_123"
    assert message.metadata == {"source": "tool"}


def test_build_outbound_message_ignores_invalid_attachment_metadata():
    response = AgentResponse(
        content="hello",
        metadata={
            OUTBOUND_MESSAGE_METADATA_KEY: {
                "media": ["", "/tmp/ok.txt", 123],
                "reply_to": 42,
                "metadata": "not-a-dict",
            }
        },
    )

    message = build_outbound_message(
        channel="feishu",
        chat_id="oc_test",
        response=response,
    )

    assert message.content == "hello"
    assert message.media == ["/tmp/ok.txt"]
    assert message.reply_to is None
    assert message.metadata == {}
