"""ACP Channel — bridges MindBot's message bus with ACP agent subprocesses.

This is not a normal chat channel. It acts as a **virtual backend** that
receives InboundMessages from other channels (Feishu, Telegram, etc.),
forwards them to an ACP agent, and sends the response back through the
original channel via the message bus.
"""

from __future__ import annotations


from loguru import logger

from mindbot.acp.config import ACPChannelConfig
from mindbot.acp.session import ACPSessionManager
from mindbot.bus.events import InboundMessage, OutboundMessage
from mindbot.bus.queue import MessageBus
from mindbot.channels.base import BaseChannel


class ACPChannel(BaseChannel):
    """ACP channel — routes messages to ACP agent subprocesses.

    The ``send()`` method is a no-op because outbound messages to this
    channel never arrive. Instead, other parts of the system call
    ``handle_prompt()`` directly to route messages through ACP.
    """

    name = "acp"

    def __init__(self, config: ACPChannelConfig, bus: MessageBus):
        super().__init__(config, bus)
        self._session_manager = ACPSessionManager(
            agents=config.agents,
            permission_policy=config.permission_policy,
            idle_timeout=config.session_idle_timeout,
        )
        self._routing = config.routing
        self._default_agent = config.default_agent
        self._show_label = config.show_label
        # Collected response text for the current prompt
        self._response_parts: list[str] = []
        self._current_agent_display: str = ""

    async def start(self) -> None:
        """Start the session manager and idle cleanup."""
        await self._session_manager.start()
        self._running = True
        logger.info("ACP channel started (agents: {})", list(self.config.agents.keys()))

    async def stop(self) -> None:
        """Stop all sessions and cleanup."""
        await self._session_manager.stop()
        self._running = False

    async def send(self, msg: OutboundMessage) -> None:
        """No-op. ACP channel does not receive outbound messages."""
        logger.debug("ACP send() called — this is expected to be a no-op")

    async def handle_prompt(self, msg: InboundMessage) -> str:
        """Process an InboundMessage through an ACP agent.

        Returns the agent's response text.
        """
        # Resolve agent name.
        agent_name = self._session_manager.resolve_agent_name(
            channel=msg.channel,
            chat_id=msg.chat_id,
            routing=self._routing,
            default=self._default_agent,
        )
        if not agent_name:
            return "(ACP: no agent configured for this chat)"

        # Get agent display name.
        agent_cfg = self._session_manager._agents.get(agent_name)
        self._current_agent_display = agent_cfg.name if agent_cfg else agent_name

        # Get or create session.
        try:
            session = await self._session_manager.get_or_create(
                chat_id=msg.chat_id,
                channel=msg.channel,
                agent_name=agent_name,
            )
        except Exception as exc:
            logger.error("ACP: failed to create session: {}", exc)
            return f"(ACP error: {exc})"

        # Collect streaming response.
        self._response_parts = []
        session.client.on_message_chunk = self._on_message_chunk

        session.is_active = True
        session.last_active_at = __import__("datetime").datetime.now()
        try:
            await session.client.prompt(session.session_id, msg.content)
        except Exception as exc:
            logger.error("ACP prompt error: {}", exc)
            return f"(ACP error: {exc})"
        finally:
            session.is_active = False

        response_text = "".join(self._response_parts)
        if not response_text:
            return "(ACP: empty response)"

        # Prepend agent label if configured.
        if self._show_label and self._current_agent_display:
            response_text = f"[{self._current_agent_display}] {response_text}"
        return response_text

    async def _on_message_chunk(self, text: str) -> None:
        """Callback: collect agent message chunks."""
        self._response_parts.append(text)
