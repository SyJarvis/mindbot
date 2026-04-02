from __future__ import annotations

from types import SimpleNamespace

from mindbot.bus.queue import MessageBus
from mindbot.channels.http import HTTPChannel


def test_http_channel_only_registers_unified_main_path_routes():
    channel = HTTPChannel(config=SimpleNamespace(), bus=MessageBus())

    route_paths = sorted(
        resource.canonical
        for resource in channel.app.router.resources()
    )

    assert route_paths == [
        "/chat",
        "/chat/stream",
        "/health",
    ]

