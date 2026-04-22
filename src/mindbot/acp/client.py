"""ACP client — orchestrates the full Agent Client Protocol lifecycle.

Spawns an ACP agent subprocess, initializes the connection, creates
sessions, sends prompts, collects streamed updates, and handles
server-to-client requests (permissions, file ops, terminals).
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Awaitable

from loguru import logger

from mindbot.acp.permission import PermissionResolver
from mindbot.acp.protocol import JsonRpcError
from mindbot.acp.transport import StdioTransport


class ACPClient:
    """High-level ACP protocol client.

    Manages one ACP agent subprocess. Multiple sessions can be created
    on a single client (though typically one session per client instance).

    Usage::

        client = ACPClient(permission_resolver=resolver)
        await client.start("npx", ["-y", "@zed-industries/claude-code-acp"], cwd="/project")
        await client.initialize()
        session_id = await client.create_session(cwd="/project")
        result = await client.prompt(session_id, "Hello!")
        await client.shutdown()
    """

    def __init__(
        self,
        permission_resolver: PermissionResolver | None = None,
        timeout: float = 300.0,
    ):
        self._transport = StdioTransport()
        self._resolver = permission_resolver or PermissionResolver()
        self._timeout = timeout
        self._agent_info: dict[str, Any] | None = None
        self._agent_capabilities: dict[str, Any] | None = None

        # Callbacks for streaming events
        self.on_message_chunk: Callable[[str], Awaitable[None]] | None = None
        self.on_thought_chunk: Callable[[str], Awaitable[None]] | None = None
        self.on_tool_call: Callable[[dict], Awaitable[None]] | None = None
        self.on_tool_call_update: Callable[[dict], Awaitable[None]] | None = None
        self.on_plan_update: Callable[[dict], Awaitable[None]] | None = None

    # -- lifecycle -----------------------------------------------------------

    async def start(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> None:
        """Spawn the agent subprocess."""
        await self._transport.start(command, args, env, cwd)
        self._register_handlers()

    async def shutdown(self) -> None:
        """Shut down the client and terminate the subprocess."""
        await self._transport.stop()

    @property
    def is_alive(self) -> bool:
        return self._transport.is_alive

    # -- ACP methods ---------------------------------------------------------

    async def initialize(self) -> dict[str, Any]:
        """Send ``initialize`` and store agent capabilities."""
        conn = self._require_connection()
        result = await conn.send_request("initialize", {
            "protocolVersion": 1,
            "clientCapabilities": {
                "fs": {"readTextFile": True, "writeTextFile": True},
                "terminal": False,
            },
            "clientInfo": {"name": "mindbot-acp", "version": "0.1.0"},
        })
        self._agent_capabilities = result.get("agentCapabilities", {})
        self._agent_info = result.get("agentInfo")
        agent_name = self._agent_info.get("name", "?") if self._agent_info else "?"
        logger.info("ACP: initialized with agent '{}'", agent_name)
        return result

    async def create_session(self, cwd: str, mcp_servers: list[dict] | None = None) -> str:
        """Send ``session/new`` and return the session ID."""
        conn = self._require_connection()
        params: dict[str, Any] = {"cwd": cwd, "mcpServers": mcp_servers or []}
        result = await conn.send_request("session/new", params)
        session_id = result.get("sessionId", "")
        logger.info("ACP: created session '{}' (cwd={})", session_id, cwd)
        return session_id

    async def prompt(self, session_id: str, content: str) -> str:
        """Send ``session/prompt`` and return the full agent response text.

        Collects ``agent_message_chunk`` updates while waiting for the
        final ``PromptResponse``. Server-to-client requests (permissions,
        file ops) are handled inline.
        """
        conn = self._require_connection()
        prompt_params = {
            "sessionId": session_id,
            "prompt": [{"type": "text", "text": content}],
        }

        # The prompt request will block until the agent finishes.
        # session/update notifications arrive in parallel via the read loop.
        try:
            result = await asyncio.wait_for(
                conn.send_request("session/prompt", prompt_params),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("ACP: prompt timed out, sending cancel")
            await conn.send_notification("session/cancel", {"sessionId": session_id})
            return "(ACP agent timed out)"
        except JsonRpcError as exc:
            logger.error("ACP prompt error: {}", exc)
            return f"(ACP error: {exc})"

        stop_reason = result.get("stopReason", "end_turn") if isinstance(result, dict) else "end_turn"
        logger.debug("ACP: prompt completed (stopReason={})", stop_reason)
        # The actual text was collected via on_message_chunk callbacks.
        return ""  # caller should collect via callbacks

    async def cancel(self, session_id: str) -> None:
        """Send ``session/cancel``."""
        conn = self._require_connection()
        await conn.send_notification("session/cancel", {"sessionId": session_id})

    # -- handler registration ------------------------------------------------

    def _register_handlers(self) -> None:
        """Register JSON-RPC handlers for server-to-client calls."""
        conn = self._require_connection()

        # session/update notifications
        conn.on_notification("session/update", self._handle_session_update)

        # Server-to-client requests
        conn.on_request("session/request_permission", self._resolver.resolve)
        conn.on_request("fs/read_text_file", self._handle_read_file)
        conn.on_request("fs/write_text_file", self._handle_write_file)
        conn.on_request("terminal/create", self._handle_terminal_create)
        conn.on_request("terminal/output", self._handle_terminal_output)
        conn.on_request("terminal/wait_for_exit", self._handle_terminal_wait)
        conn.on_request("terminal/kill", self._handle_terminal_kill)
        conn.on_request("terminal/release", self._handle_terminal_release)

    # -- notification handlers -----------------------------------------------

    async def _handle_session_update(self, params: dict) -> None:
        """Dispatch session/update notifications to callbacks."""
        update = params.get("update", params)
        update_type = update.get("sessionUpdate")

        if update_type == "agent_message_chunk":
            text = self._extract_text(update.get("content", {}))
            if text and self.on_message_chunk:
                await self.on_message_chunk(text)

        elif update_type == "agent_thought_chunk":
            text = self._extract_text(update.get("content", {}))
            if text and self.on_thought_chunk:
                await self.on_thought_chunk(text)

        elif update_type == "tool_call":
            if self.on_tool_call:
                await self.on_tool_call(update)

        elif update_type == "tool_call_update":
            if self.on_tool_call_update:
                await self.on_tool_call_update(update)

        elif update_type == "plan":
            if self.on_plan_update:
                await self.on_plan_update(update)

        else:
            logger.debug("ACP: unhandled sessionUpdate type '{}'", update_type)

    # -- server-to-client request handlers -----------------------------------

    async def _handle_read_file(self, params: dict) -> dict:
        """Handle ``fs/read_text_file`` by reading from the local filesystem."""
        from pathlib import Path
        path = params.get("path", "")
        try:
            content = Path(path).read_text(encoding="utf-8")
            return {"content": content}
        except FileNotFoundError:
            return {"content": "", "_error": f"file not found: {path}"}
        except Exception as exc:
            logger.error("ACP read_file error: {}", exc)
            return {"content": "", "_error": str(exc)}

    async def _handle_write_file(self, params: dict) -> dict:
        """Handle ``fs/write_text_file`` by writing to the local filesystem."""
        from pathlib import Path
        path = params.get("path", "")
        content = params.get("content", "")
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(content, encoding="utf-8")
            return {}
        except Exception as exc:
            logger.error("ACP write_file error: {}", exc)
            return {"_error": str(exc)}

    async def _handle_terminal_create(self, params: dict) -> dict:
        """Reject terminal creation (MindBot runs as a server)."""
        logger.warning("ACP: terminal/create rejected (not supported in server mode)")
        return {"_error": "terminal operations not supported"}

    async def _handle_terminal_output(self, params: dict) -> dict:
        return {"output": "", "truncated": False}

    async def _handle_terminal_wait(self, params: dict) -> dict:
        return {"exitCode": 1}

    async def _handle_terminal_kill(self, params: dict) -> dict:
        return {}

    async def _handle_terminal_release(self, params: dict) -> dict:
        return {}

    # -- helpers -------------------------------------------------------------

    def _require_connection(self) -> Any:
        """Return the JsonRpcConnection or raise."""
        if not self._transport.connection or self._transport.connection.is_closed:
            raise ConnectionError("ACP client not connected")
        return self._transport.connection

    @staticmethod
    def _extract_text(content: dict | str) -> str:
        """Extract text from a content block."""
        if isinstance(content, str):
            return content
        return content.get("text", "") if isinstance(content, dict) else ""
