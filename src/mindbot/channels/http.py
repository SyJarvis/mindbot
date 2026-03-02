"""HTTP API channel for MindBot."""

import asyncio
import json
import uuid
from aiohttp import web
from typing import Any

from loguru import logger

from mindbot.bus.events import OutboundMessage
from mindbot.bus.queue import MessageBus
from mindbot.channels.base import BaseChannel
from mindbot.agent.models import AgentEvent, EventType


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
    - Tool approval management
    - User input handling
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
        # Store pending approval/input requests
        self._pending_approvals: dict[str, asyncio.Future] = {}
        self._pending_inputs: dict[str, asyncio.Future] = {}
        # Reference to agent
        self._agent_ref: Any = None
        self._setup_routes()

    def set_agent(self, agent: Any) -> None:
        """Set reference to agent for approval/input resolution."""
        self._agent_ref = agent

    def _setup_routes(self) -> None:
        """Setup HTTP routes."""
        self.app.router.add_post("/chat", self.handle_chat)
        self.app.router.add_post("/chat/stream", self.handle_chat_stream)
        self.app.router.add_get("/health", self.handle_health)
        self.app.router.add_get("/memory/search", self.handle_memory_search)
        # Approval endpoints
        self.app.router.add_post("/approval/{request_id}", self.handle_approval)
        self.app.router.add_get("/approval/pending", self.handle_pending_approvals)
        # Input endpoints
        self.app.router.add_post("/input/{request_id}", self.handle_user_input)

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
            # Check if agent is configured
            if self._agent_ref is None:
                # No agent set - return a simple test stream for testing
                # This allows the HTTP endpoint to work even without a configured agent
                test_chunks = [
                    "Hello! ",
                    "This is a test ",
                    "stream response ",
                    "without an agent configured.",
                ]

                for chunk in test_chunks:
                    chunk_data = json.dumps({
                        "type": "delta",
                        "content": chunk,
                    })
                    await response.write(f"event: delta\n".encode())
                    await response.write(f"data: {chunk_data}\n\n".encode())
                    await response.drain()  # Flush data to client
                    # Small delay to ensure chunks arrive separately
                    await asyncio.sleep(0.01)

                # Send done signal
                done_data = json.dumps({"type": "done"})
                await response.write(f"event: done\n".encode())
                await response.write(f"data: {done_data}\n\n".encode())
                await response.drain()  # Flush data to client
            else:
                # Use agent's chat method with event callback
                events_buffer: list[AgentEvent] = []

                async def event_callback(event: AgentEvent) -> None:
                    """Send events as SSE."""
                    events_buffer.append(event)
                    event_data = json.dumps({
                        "type": event.type.value,
                        "data": event.data,
                        "timestamp": event.timestamp,
                    })
                    await response.write(f"event: {event.type.value}\n".encode())
                    await response.write(f"data: {event_data}\n\n".encode())
                    await response.drain()  # Flush data to client

                agent_response = await self._agent_ref.chat(
                    message=content,
                    session_id=session_id,
                    on_event=event_callback,
                )

                # Send final response
                final_data = json.dumps({
                    "type": "final",
                    "content": agent_response.content,
                    "stop_reason": agent_response.stop_reason.value,
                })
                await response.write(f"event: final\n".encode())
                await response.write(f"data: {final_data}\n\n".encode())
                await response.drain()  # Flush data to client

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

    async def handle_approval(self, request: web.Request) -> web.Response:
        """Handle tool approval response."""
        request_id = request.match_info["request_id"]
        session_id = request.query.get("session_id", "default")

        try:
            data = await request.json()
            decision = data.get("decision", "deny")  # allow_once, allow_always, deny
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        if decision not in ["allow_once", "allow_always", "deny"]:
            return web.json_response({"error": "Invalid decision"}, status=400)

        # Resolve the approval
        if self._agent_ref:
            self._agent_ref.resolve_approval(request_id, decision, session_id)

            # Check if there's a pending future for this request
            if request_id in self._pending_approvals:
                future = self._pending_approvals.pop(request_id)
                if not future.done():
                    future.set_result(decision)

        return web.json_response({"status": "resolved", "request_id": request_id})

    async def handle_pending_approvals(self, request: web.Request) -> web.Response:
        """Get pending approval requests."""
        session_id = request.query.get("session_id", "default")

        pending = []
        for req_id, future in self._pending_approvals.items():
            if not future.done():
                pending.append({"request_id": req_id})

        return web.json_response({"pending": pending})

    async def handle_user_input(self, request: web.Request) -> web.Response:
        """Handle user input response."""
        request_id = request.match_info["request_id"]
        session_id = request.query.get("session_id", "default")

        try:
            data = await request.json()
            input_text = data.get("input", "")
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        # Provide the input
        if self._agent_ref:
            self._agent_ref.provide_input(request_id, input_text, session_id)

            # Check if there's a pending future for this request
            if request_id in self._pending_inputs:
                future = self._pending_inputs.pop(request_id)
                if not future.done():
                    future.set_result(input_text)

        return web.json_response({"status": "provided", "request_id": request_id})

    async def _wait_for_approval(self, request_id: str, timeout: float = 300) -> str:
        """Wait for approval response."""
        future: asyncio.Future[str] = asyncio.Future()
        self._pending_approvals[request_id] = future

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            return "deny"
        finally:
            self._pending_approvals.pop(request_id, None)

    async def _wait_for_user_input(self, request_id: str, timeout: float = 300) -> str:
        """Wait for user input."""
        future: asyncio.Future[str] = asyncio.Future()
        self._pending_inputs[request_id] = future

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            return ""
        finally:
            self._pending_inputs.pop(request_id, None)

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

    async def handle_memory_search(self, request: web.Request) -> web.Response:
        """Search memory endpoint."""
        query = request.query.get("q", "")
        limit = int(request.query.get("limit", 10))

        if not query:
            return web.json_response({"error": "query parameter 'q' is required"}, status=400)

        # This would integrate with the memory system
        return web.json_response({
            "query": query,
            "results": [],
            "count": 0
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
