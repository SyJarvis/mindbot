"""ACP (Agent Client Protocol) client for MindBot.

Enables MindBot to connect to ACP-compatible agents (Claude Code, Codex, etc.)
and route chat messages through them.
"""

from mindbot.acp.channel import ACPChannel
from mindbot.acp.client import ACPClient
from mindbot.acp.config import ACPChannelConfig
from mindbot.acp.session import ACPSessionManager

__all__ = ["ACPChannel", "ACPClient", "ACPChannelConfig", "ACPSessionManager"]
