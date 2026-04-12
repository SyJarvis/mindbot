"""JSON-RPC 2.0 protocol over NDJSON framing for ACP.

Provides the low-level message transport: reading/writing JSON-RPC
messages as newline-delimited JSON over async streams, correlating
requests with responses by ID, and dispatching notifications and
server-to-client requests to registered handlers.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger


class JsonRpcError(Exception):
    """JSON-RPC error."""

    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.data = data


class JsonRpcConnection:
    """NDJSON-framed JSON-RPC 2.0 connection.

    Reads JSON-RPC messages from *reader* (async line iterator) and
    writes to *writer* (async writer). Maintains a table of pending
    request futures keyed by ID so responses can be resolved.

    Server-to-client requests (agent → client) and notifications are
    dispatched to callbacks registered via ``on_request`` / ``on_notification``.
    """

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ):
        self._reader = reader
        self._writer = writer
        self._next_id = 1
        self._pending: dict[int | str, asyncio.Future[Any]] = {}
        self._notification_handlers: dict[str, Callable[..., Awaitable[None]]] = {}
        self._request_handlers: dict[str, Callable[..., Awaitable[Any]]] = {}
        self._read_task: asyncio.Task[None] | None = None
        self._closed = False

    # -- public API ----------------------------------------------------------

    async def start(self) -> None:
        """Start the background read loop."""
        self._read_task = asyncio.create_task(self._read_loop())

    async def close(self) -> None:
        """Close the connection and cancel the read loop."""
        self._closed = True
        if self._read_task and not self._read_task.done():
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
        # Reject all pending futures.
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(ConnectionError("connection closed"))
        self._pending.clear()
        try:
            self._writer.close()
            await self._writer.wait_closed()
        except Exception:
            pass

    async def send_request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Send a JSON-RPC request and return the result (or raise on error)."""
        msg_id = self._next_id
        self._next_id += 1
        msg: dict[str, Any] = {"jsonrpc": "2.0", "id": msg_id, "method": method}
        if params is not None:
            msg["params"] = params
        await self._write(msg)
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Any] = loop.create_future()
        self._pending[msg_id] = fut
        return await fut

    async def send_notification(self, method: str, params: dict[str, Any] | None = None) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        await self._write(msg)

    async def send_response(self, msg_id: int | str, result: Any) -> None:
        """Send a success response for a server-to-client request."""
        await self._write({"jsonrpc": "2.0", "id": msg_id, "result": result})

    async def send_error(self, msg_id: int | str, code: int, message: str, data: Any = None) -> None:
        """Send an error response for a server-to-client request."""
        err: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            err["data"] = data
        await self._write({"jsonrpc": "2.0", "id": msg_id, "error": err})

    def on_notification(self, method: str, handler: Callable[..., Awaitable[None]]) -> None:
        """Register a handler for incoming notifications with *method*."""
        self._notification_handlers[method] = handler

    def on_request(self, method: str, handler: Callable[..., Awaitable[Any]]) -> None:
        """Register a handler for incoming server-to-client requests with *method*."""
        self._request_handlers[method] = handler

    @property
    def is_closed(self) -> bool:
        return self._closed

    # -- internal ------------------------------------------------------------

    async def _write(self, msg: dict[str, Any]) -> None:
        data = json.dumps(msg, ensure_ascii=False) + "\n"
        self._writer.write(data.encode("utf-8"))
        await self._writer.drain()

    async def _read_loop(self) -> None:
        """Background task: read NDJSON lines, dispatch to handlers."""
        try:
            while not self._closed:
                line_bytes = await self._reader.readline()
                if not line_bytes:
                    logger.debug("ACP transport: EOF received")
                    break
                line = line_bytes.decode("utf-8").strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError as exc:
                    logger.warning("ACP: invalid JSON from agent: {} | {}", exc, line[:200])
                    continue
                await self._dispatch(msg)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("ACP read loop error: {}", exc)
        finally:
            self._closed = True
            # Reject pending.
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(ConnectionError("ACP connection lost"))
            self._pending.clear()

    async def _dispatch(self, msg: dict[str, Any]) -> None:
        """Route an incoming JSON-RPC message to the right handler."""
        msg_id = msg.get("id")

        # 1. Response to our request
        if "result" in msg or "error" in msg:
            if msg_id is not None and msg_id in self._pending:
                fut = self._pending.pop(msg_id)
                if "error" in msg:
                    err = msg["error"]
                    if not fut.done():
                        fut.set_exception(
                            JsonRpcError(
                                code=err.get("code", -1),
                                message=err.get("message", "unknown error"),
                                data=err.get("data"),
                            )
                        )
                else:
                    if not fut.done():
                        fut.set_result(msg.get("result"))
            return

        # 2. Notification (has method, no id or id is None)
        method = msg.get("method")
        if method and msg_id is None:
            handler = self._notification_handlers.get(method)
            if handler:
                try:
                    await handler(msg.get("params", {}))
                except Exception as exc:
                    logger.error("ACP notification handler '{}' error: {}", method, exc)
            else:
                logger.debug("ACP: unhandled notification '{}'", method)
            return

        # 3. Server-to-client request (has method AND id)
        if method and msg_id is not None:
            handler = self._request_handlers.get(method)
            if handler:
                try:
                    result = await handler(msg.get("params", {}))
                    await self.send_response(msg_id, result)
                except Exception as exc:
                    logger.error("ACP request handler '{}' error: {}", method, exc)
                    await self.send_error(msg_id, -32603, str(exc))
            else:
                logger.warning("ACP: unhandled server request '{}'", method)
                await self.send_error(msg_id, -32601, f"method not found: {method}")
            return

        logger.debug("ACP: unclassifiable message: {}", {k: v for k, v in msg.items() if k != "params"})
