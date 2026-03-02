"""Message bus for channel-agent communication."""

from mindbot.bus.events import InboundMessage, OutboundMessage
from mindbot.bus.queue import MessageBus

__all__ = [
    "InboundMessage",
    "OutboundMessage",
    "MessageBus",
]
