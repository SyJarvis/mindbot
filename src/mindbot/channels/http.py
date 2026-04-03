"""HTTP API channel for MindBot."""

from collections.abc import AsyncIterator, Awaitable, Callable
import asyncio
import json
from typing import Any

from aiohttp import web

from loguru import logger

from mindbot.bus.events import OutboundMessage
from mindbot.bus.queue import MessageBus
from mindbot.channels.base import BaseChannel


async def cors_middleware(app: web.Application, handler: Any) -> Any:
    """CORS middleware to allow cross-origin requests."""
    async def middleware_handler(request: web.Request) -> web.Response:
        # Handle preflight OPTIONS request
        if request.method == "OPTIONS":
            response = web.Response(status=200)
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
            return response

        # For all other requests, let the handler process first
        response = await handler(request)

        # Add CORS headers to response
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"

        return response
    return middleware_handler


class HTTPChannel(BaseChannel):
    """HTTP API channel using aiohttp.

    Provides REST endpoints for:
    - Chat with streaming support
    - Health checks
    """

    name: str = "http"

    def __init__(self, config: Any, bus: MessageBus):
        super().__init__(config, bus)
        # Create app with CORS middleware
        middlewares = [cors_middleware]
        self.app = web.Application(middlewares=middlewares)
        self.runner: web.AppRunner | None = None
        # Store pending response futures by chat_id
        self._pending_requests: dict[str, asyncio.Queue] = {}
        self._chat_handler: Callable[[str, str], Awaitable[Any]] | None = None
        self._chat_stream_handler: Callable[[str, str], AsyncIterator[str]] | None = None
        self._setup_routes()

    def set_chat_handlers(
        self,
        *,
        chat_handler: Callable[[str, str], Awaitable[Any]] | None = None,
        stream_handler: Callable[[str, str], AsyncIterator[str]] | None = None,
    ) -> None:
        """Attach shared chat handlers from the unified main path."""
        self._chat_handler = chat_handler
        self._chat_stream_handler = stream_handler

    def _setup_routes(self) -> None:
        """Setup HTTP routes."""
        self.app.router.add_post("/chat", self.handle_chat)
        self.app.router.add_post("/chat/stream", self.handle_chat_stream)
        self.app.router.add_get("/health", self.handle_health)

    async def _wait_for_response(self, chat_id: str, timeout: float = 30.0) -> OutboundMessage | None:
        """Wait for a response from the agent."""
        queue = asyncio.Queue()
        self._pending_requests[chat_id] = queue

        try:
            # Wait for response with timeout
            response = await asyncio.wait_for(queue.get(), timeout=timeout)
            return response
        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for response for chat_id {chat_id}")
            return None
        finally:
            # Clean up
            self._pending_requests.pop(chat_id, None)

    async def handle_chat(self, request: web.Request) -> web.Response:
        """Handle chat request."""
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        content = data.get("content", "")
        chat_id = data.get("chat_id", "http")
        session_id = data.get("session_id", "default")

        if not content:
            return web.json_response({"error": "content is required"}, status=400)

        if self._chat_handler is not None:
            agent_response = await self._chat_handler(content, session_id)
            return web.json_response({
                "content": agent_response.content,
                "chat_id": chat_id,
                "status": "success",
            })

        # Send to message bus
        await self._handle_message(
            sender_id="http_user",
            chat_id=chat_id,
            content=content,
            metadata={"session_id": session_id, "stream": False}
        )

        # Wait for response from agent
        response_msg = await self._wait_for_response(chat_id, timeout=30.0)

        if response_msg:
            return web.json_response({
                "content": response_msg.content,
                "chat_id": chat_id,
                "status": "success"
            })
        else:
            return web.json_response({
                "error": "Timeout waiting for response",
                "chat_id": chat_id
            }, status=504)

    async def handle_chat_stream(self, request: web.Request) -> web.Response:
        """Handle streaming chat request with real-time streaming and events."""
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        content = data.get("content", "")
        chat_id = data.get("chat_id", "http")
        session_id = data.get("session_id", "default")

        if not content:
            return web.json_response({"error": "content is required"}, status=400)

        if self._chat_stream_handler is None:
            return web.json_response(
                {"error": "streaming handler is not configured"},
                status=503,
            )

        # Return streaming response with CORS headers
        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization",
            }
        )

        await response.prepare(request)

        try:
            async for chunk in self._chat_stream_handler(content, session_id):
                chunk_data = json.dumps({
                    "type": "delta",
                    "content": chunk,
                })
                await response.write(f"event: delta\n".encode())
                await response.write(f"data: {chunk_data}\n\n".encode())
                await response.drain()

            done_data = json.dumps({"type": "done", "chat_id": chat_id})
            await response.write(f"event: done\n".encode())
            await response.write(f"data: {done_data}\n\n".encode())
            await response.drain()

        except Exception as e:
            logger.exception(f"Stream error: {e}")
            # Send error message
            error_data = json.dumps({
                "type": "error",
                "error": str(e),
            })
            await response.write(f"event: error\n".encode())
            await response.write(f"data: {error_data}\n\n".encode())
            await response.drain()  # Flush data to client

        await response.write_eof()
        return response

    async def handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        return web.json_response({
            "status": "healthy",
            "channel": self.name,
            "bus": {
                "inbound": self.bus.inbound_size,
                "outbound": self.bus.outbound_size
            },
            "pending_requests": len(self._pending_requests)
        })

    async def start(self) -> None:
        """Start the HTTP server."""
        host = getattr(self.config, "host", "0.0.0.0")
        port = getattr(self.config, "port", 31211)

        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, host, port)
        await site.start()

        self._running = True
        logger.info(f"HTTP channel listening on http://{host}:{port}")

    async def stop(self) -> None:
        """Stop the HTTP server."""
        if self.runner:
            await self.runner.cleanup()
        self._running = False
        logger.info("HTTP channel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """Handle outbound message from the agent."""
        chat_id = msg.chat_id

        # Check if there's a pending request for this chat_id
        if chat_id in self._pending_requests:
            queue = self._pending_requests[chat_id]
            await queue.put(msg)
            logger.debug(f"Delivered response to chat_id {chat_id}")
        else:
            # No pending request, this might be a proactive message
            logger.debug(f"No pending request for chat_id {chat_id}, message not delivered")
