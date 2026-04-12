"""Channel manager for coordinating chat channels."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from mindbot.bus.events import InboundMessage, OutboundMessage
from mindbot.bus.outbound import build_outbound_message
from mindbot.bus.queue import MessageBus
from mindbot.channels.base import BaseChannel


class ChannelManager:
    """Manages chat channels and coordinates message routing.

    Responsibilities:
    - Initialize enabled channels (HTTP, CLI, Telegram, etc.)
    - Start/stop channels
    - Route outbound messages
    """

    def __init__(self, config: Any, bus: MessageBus):
        self.config = config
        self.bus = bus
        self.channels: dict[str, BaseChannel] = {}
        self._dispatch_task: asyncio.Task | None = None
        self._inbound_task: asyncio.Task | None = None
        self._chat_handler: Callable[[str, str], Awaitable[Any]] | None = None

        self._init_channels()

    def _init_channels(self) -> None:
        """Initialize channels based on config."""
        # Get channel configs from the config object
        channels_config = getattr(self.config, "channels", None)
        if not channels_config:
            # Simple config without channels section
            return

        # HTTP channel
        http_config = getattr(channels_config, "http", None)
        if http_config and getattr(http_config, "enabled", False):
            try:
                from mindbot.channels.http import HTTPChannel
                self.channels["http"] = HTTPChannel(http_config, self.bus)
                logger.info("HTTP channel enabled")
            except ImportError as e:
                logger.warning(f"HTTP channel not available: {e}")

        # CLI channel (stdin/stdout)
        cli_config = getattr(channels_config, "cli", None)
        if cli_config and getattr(cli_config, "enabled", False):
            try:
                from mindbot.channels.cli import CLIChannel
                self.channels["cli"] = CLIChannel(cli_config, self.bus)
                logger.info("CLI channel enabled")
            except ImportError as e:
                logger.warning(f"CLI channel not available: {e}")

        # Telegram channel
        telegram_config = getattr(channels_config, "telegram", None)
        if telegram_config and getattr(telegram_config, "enabled", False):
            try:
                from mindbot.channels.telegram import TelegramChannel
                self.channels["telegram"] = TelegramChannel(telegram_config, self.bus)
                logger.info("Telegram channel enabled")
            except ImportError as e:
                logger.warning(f"Telegram channel not available: {e}")

        # Feishu channel
        feishu_config = getattr(channels_config, "feishu", None)
        if feishu_config and getattr(feishu_config, "enabled", False):
            try:
                from mindbot.channels.feishu import FeishuChannel
                self.channels["feishu"] = FeishuChannel(feishu_config, self.bus)
                logger.info("Feishu channel enabled")
            except ImportError as e:
                logger.warning(f"Feishu channel not available: {e}")

        # ACP channel (Agent Client Protocol)
        acp_config = getattr(channels_config, "acp", None)
        if acp_config and getattr(acp_config, "enabled", False):
            try:
                from mindbot.acp.channel import ACPChannel
                self.channels["acp"] = ACPChannel(acp_config, self.bus)
                logger.info("ACP channel enabled")
            except ImportError as e:
                logger.warning(f"ACP channel not available: {e}")

    async def _start_channel(self, name: str, channel: BaseChannel) -> None:
        """Start a channel and log any exceptions."""
        try:
            await channel.start()
        except Exception as e:
            logger.error(f"Failed to start channel {name}: {e}")

    async def start_all(self) -> None:
        """Start all channels and the bus dispatchers."""
        if not self.channels:
            logger.warning("No channels enabled")
            return

        if self._chat_handler is None:
            logger.warning("No inbound chat handler configured; inbound bus messages will be ignored")

        # Start inbound/outbound dispatchers before channels begin publishing.
        self._inbound_task = asyncio.create_task(self._dispatch_inbound())

        # Start outbound dispatcher
        self._dispatch_task = asyncio.create_task(self._dispatch_outbound())

        # Start channels
        tasks = []
        for name, channel in self.channels.items():
            logger.info(f"Starting {name} channel...")
            tasks.append(asyncio.create_task(self._start_channel(name, channel)))

        # Wait for all to complete (they should run forever)
        await asyncio.gather(*tasks, return_exceptions=True)

    async def stop_all(self) -> None:
        """Stop all channels and the bus dispatchers."""
        logger.info("Stopping all channels...")

        # Stop inbound dispatcher
        if self._inbound_task:
            self._inbound_task.cancel()
            try:
                await self._inbound_task
            except asyncio.CancelledError:
                pass

        # Stop dispatcher
        if self._dispatch_task:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass

        # Stop all channels
        for name, channel in self.channels.items():
            try:
                await channel.stop()
                logger.info(f"Stopped {name} channel")
            except Exception as e:
                logger.error(f"Error stopping {name}: {e}")

    async def _dispatch_outbound(self) -> None:
        """Dispatch outbound messages to the appropriate channel."""
        logger.info("Outbound dispatcher started")

        while True:
            try:
                msg = await asyncio.wait_for(
                    self.bus.consume_outbound(),
                    timeout=1.0
                )

                channel = self.channels.get(msg.channel)
                if channel:
                    try:
                        await channel.send(msg)
                    except Exception as e:
                        logger.error(f"Error sending to {msg.channel}: {e}")
                else:
                    logger.warning(f"Unknown channel: {msg.channel}")

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    async def _dispatch_inbound(self) -> None:
        """Consume inbound bus messages and route them through the unified chat handler."""
        logger.info("Inbound dispatcher started")

        while True:
            try:
                msg = await asyncio.wait_for(
                    self.bus.consume_inbound(),
                    timeout=1.0,
                )

                if self._chat_handler is None:
                    logger.warning(f"Dropping inbound message from {msg.channel}: no chat handler configured")
                    continue

                # Check ACP routing
                acp_channel = self.channels.get("acp")
                if acp_channel and self._should_route_acp(msg):
                    try:
                        response = await acp_channel.handle_prompt(msg)
                        reply = build_outbound_message(
                            channel=msg.channel,
                            chat_id=msg.chat_id,
                            response=response,
                        )
                    except Exception as e:
                        logger.error(f"ACP error handling message from {msg.channel}: {e}")
                        reply = OutboundMessage(
                            channel=msg.channel,
                            chat_id=msg.chat_id,
                            content=f"ACP Error: {e}",
                        )
                    await self.bus.publish_outbound(reply)
                    continue

                session_id = msg.metadata.get("session_id", "default")
                try:
                    response = await self._chat_handler(msg.content, session_id)
                    reply = build_outbound_message(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        response=response,
                    )
                except Exception as e:
                    logger.error(f"Error handling inbound message from {msg.channel}: {e}")
                    reply = OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content=f"Error: {e}",
                    )

                await self.bus.publish_outbound(reply)

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    def _should_route_acp(self, msg: InboundMessage) -> bool:
        """Check if an inbound message should be routed to ACP."""
        acp_channel = self.channels.get("acp")
        if not acp_channel:
            return False
        config = getattr(acp_channel, "config", None)
        if not config:
            return False
        routing = getattr(config, "routing", {})
        default_agent = getattr(config, "default_agent", None)

        # Check exact match
        exact = f"{msg.channel}:{msg.chat_id}"
        if exact in routing:
            return True
        # Check wildcard pattern
        pattern = f"{msg.channel}:*"
        if pattern in routing:
            return True
        # Route to default agent if configured
        if default_agent:
            return False  # Only route if explicit routing rules match
        return False

    def set_chat_handler(
        self,
        handler: Callable[[str, str], Awaitable[Any]],
    ) -> None:
        """Set the shared chat handler used for inbound bus messages."""
        self._chat_handler = handler

    def get_channel(self, name: str) -> BaseChannel | None:
        """Get a channel by name."""
        return self.channels.get(name)

    def get_status(self) -> dict[str, Any]:
        """Get status of all channels."""
        return {
            name: {
                "enabled": True,
                "running": channel.is_running
            }
            for name, channel in self.channels.items()
        }

    @property
    def enabled_channels(self) -> list[str]:
        """Get list of enabled channel names."""
        return list(self.channels.keys())
