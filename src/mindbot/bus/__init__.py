"""Message bus for channel-agent communication."""

from src.mindbot.bus.events import InboundMessage, OutboundMessage
from src.mindbot.bus.outbound import OUTBOUND_MESSAGE_METADATA_KEY, build_outbound_message
from src.mindbot.bus.queue import MessageBus

__all__ = [
    "InboundMessage",
    "OutboundMessage",
    "OUTBOUND_MESSAGE_METADATA_KEY",
    "MessageBus",
    "build_outbound_message",
]
