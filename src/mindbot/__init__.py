"""MindBot - AI Assistant (Native Implementation)."""

__version__ = "0.2.0"

__logo__ = """
╔════════════════════════════════════╗
║            MindBot                ║
╚════════════════════════════════════╝
"""

from src.mindbot.bot import MindBot
from src.mindbot.config.schema import Config
from src.mindbot.bus import MessageBus, InboundMessage, OutboundMessage
from src.mindbot.channels import BaseChannel, ChannelManager

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
