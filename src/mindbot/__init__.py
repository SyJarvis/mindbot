"""MindBot - AI Assistant (Native Implementation)."""

__version__ = "0.3.3"

__logo__ = """
╔════════════════════════════════════╗
║            MindBot                ║
╚════════════════════════════════════╝
"""

from mindbot.bot import MindBot
from mindbot.config.schema import Config
from mindbot.bus import MessageBus, InboundMessage, OutboundMessage
from mindbot.channels import BaseChannel, ChannelManager

__all__ = [
    "MindBot",
    "Config",
    "MessageBus",
    "InboundMessage",
    "OutboundMessage",
    "BaseChannel",
    "ChannelManager",
    "__version__",
    "__logo__",
]
