"""CLI channel for MindBot.

Simple final-text transport: reads lines from stdin, publishes them to the
message bus, and prints outbound message content to stdout.
"""

import asyncio
from typing import Any

from loguru import logger

from src.mindbot.bus.events import OutboundMessage
from src.mindbot.bus.queue import MessageBus
from src.mindbot.channels.base import BaseChannel


class CLIChannel(BaseChannel):
    """CLI (stdin/stdout) channel for interactive terminal use.

    Renders only the final assistant text; streaming events are handled
    upstream by the unified main path and are not re-rendered here.
    """

    name: str = "cli"

    def __init__(self, config: Any, bus: MessageBus):
        super().__init__(config, bus)
        self._input_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the CLI channel."""
        self._running = True
        self._input_task = asyncio.create_task(self._read_input())
        logger.info("CLI channel started")

    async def stop(self) -> None:
        """Stop the CLI channel."""
        self._running = False

        if self._input_task:
            self._input_task.cancel()
            try:
                await self._input_task
            except asyncio.CancelledError:
                pass
        logger.info("CLI channel stopped")

    async def _read_input(self) -> None:
        """Read input from stdin and send to message bus."""
        loop = asyncio.get_event_loop()

        while self._running:
            try:
                line = await loop.run_in_executor(None, input, ">>> ")

                if not line.strip():
                    continue

                if line.strip().lower() in ["exit", "quit", "bye"]:
                    break

                await self._handle_message(
                    sender_id="cli_user",
                    chat_id="cli",
                    content=line.strip(),
                    metadata={"session_id": "default"},
                )

            except EOFError:
                break
            except KeyboardInterrupt:
                print("\n[Operation aborted]")
            except Exception as e:
                logger.error(f"Error reading CLI input: {e}")

    async def send(self, msg: OutboundMessage) -> None:
        """Render the final assistant text to stdout."""
        if msg.content:
            print(f"\n{msg.content}\n>>> ", end="")
