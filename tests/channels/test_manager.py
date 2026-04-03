from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from mindbot.agent.models import AgentResponse
from mindbot.bus.events import InboundMessage
from mindbot.bus.queue import MessageBus
from mindbot.channels.base import BaseChannel
from mindbot.channels.manager import ChannelManager


class FakeChannel(BaseChannel):
    name = "fake"

    def __init__(self, bus: MessageBus):
        super().__init__(config=SimpleNamespace(), bus=bus)
        self.sent_messages = []

    async def start(self) -> None:
        self._running = True
        while self._running:
            await asyncio.sleep(0.01)

    async def stop(self) -> None:
        self._running = False

    async def send(self, msg) -> None:
        self.sent_messages.append(msg)


@pytest.mark.asyncio
async def test_channel_manager_routes_inbound_bus_messages_through_chat_handler():
    bus = MessageBus()
    manager = ChannelManager(config=SimpleNamespace(), bus=bus)
    fake_channel = FakeChannel(bus)
    manager.channels["fake"] = fake_channel

    async def chat_handler(message: str, session_id: str) -> AgentResponse:
        return AgentResponse(content=f"{session_id}:{message}")

    manager.set_chat_handler(chat_handler)
    start_task = asyncio.create_task(manager.start_all())

    try:
        await bus.publish_inbound(
            InboundMessage(
                channel="fake",
                sender_id="user-1",
                chat_id="chat-1",
                content="hello",
                metadata={"session_id": "session-42"},
            )
        )

        for _ in range(50):
            if fake_channel.sent_messages:
                break
            await asyncio.sleep(0.01)

        assert len(fake_channel.sent_messages) == 1
        assert fake_channel.sent_messages[0].content == "session-42:hello"
    finally:
        await manager.stop_all()
        await start_task

