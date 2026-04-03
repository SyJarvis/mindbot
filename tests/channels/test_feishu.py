from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mindbot.bus.events import OutboundMessage
from mindbot.bus.queue import MessageBus
from mindbot.channels.feishu import FeishuChannel


def _make_channel() -> FeishuChannel:
    channel = FeishuChannel(config=SimpleNamespace(), bus=MessageBus())
    channel._client = object()
    return channel


@pytest.mark.asyncio
async def test_send_media_only_uploads_and_sends_native_attachment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    channel = _make_channel()
    image_path = tmp_path / "diagram.png"
    image_path.write_bytes(b"fake-image")

    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(channel, "_upload_image_sync", lambda file_path: "img_123")

    def record_send(receive_id_type: str, receive_id: str, msg_type: str, content: str) -> bool:
        calls.append((msg_type, content))
        return True

    monkeypatch.setattr(channel, "_send_message_sync", record_send)

    await channel.send(
        OutboundMessage(
            channel="feishu",
            chat_id="oc_chat",
            content="",
            media=[str(image_path)],
        )
    )

    assert calls == [("image", json.dumps({"image_key": "img_123"}, ensure_ascii=False))]


@pytest.mark.asyncio
async def test_send_text_and_media_as_separate_operations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    channel = _make_channel()
    file_path = tmp_path / "report.pdf"
    file_path.write_bytes(b"fake-pdf")

    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(channel, "_upload_file_sync", lambda file_path: "file_123")

    def record_send(receive_id_type: str, receive_id: str, msg_type: str, content: str) -> bool:
        calls.append((msg_type, content))
        return True

    monkeypatch.setattr(channel, "_send_message_sync", record_send)

    await channel.send(
        OutboundMessage(
            channel="feishu",
            chat_id="oc_chat",
            content="hello file",
            media=[str(file_path)],
        )
    )

    assert [msg_type for msg_type, _ in calls] == ["interactive", "file"]
    interactive_body = json.loads(calls[0][1])
    assert interactive_body["elements"]
    assert calls[1][1] == json.dumps({"file_key": "file_123"}, ensure_ascii=False)


@pytest.mark.asyncio
async def test_send_skips_missing_attachment_and_still_delivers_text(monkeypatch: pytest.MonkeyPatch):
    channel = _make_channel()
    calls: list[tuple[str, str]] = []

    def record_send(receive_id_type: str, receive_id: str, msg_type: str, content: str) -> bool:
        calls.append((msg_type, content))
        return True

    monkeypatch.setattr(channel, "_send_message_sync", record_send)

    await channel.send(
        OutboundMessage(
            channel="feishu",
            chat_id="oc_chat",
            content="caption",
            media=["https://example.com/report.pdf"],
        )
    )

    assert [msg_type for msg_type, _ in calls] == ["interactive"]


@pytest.mark.asyncio
async def test_send_handles_upload_failure_without_sending_attachment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    channel = _make_channel()
    file_path = tmp_path / "report.pdf"
    file_path.write_bytes(b"fake-pdf")
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(channel, "_upload_file_sync", lambda file_path: None)

    def record_send(receive_id_type: str, receive_id: str, msg_type: str, content: str) -> bool:
        calls.append((msg_type, content))
        return True

    monkeypatch.setattr(channel, "_send_message_sync", record_send)

    await channel.send(
        OutboundMessage(
            channel="feishu",
            chat_id="oc_chat",
            content="caption",
            media=[str(file_path)],
        )
    )

    assert [msg_type for msg_type, _ in calls] == ["interactive"]
