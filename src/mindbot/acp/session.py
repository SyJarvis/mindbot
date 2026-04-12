"""ACP session manager — tracks per-chat sessions and their agent subprocesses."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime

from loguru import logger

from mindbot.acp.client import ACPClient
from mindbot.acp.config import ACPAgentConfig, ACPPermissionPolicy
from mindbot.acp.permission import PermissionResolver


@dataclass
class ACPSession:
    """One ACP session bound to a chat."""

    session_id: str  # ACP session ID
    chat_id: str  # MindBot chat_id
    channel: str  # Origin channel (feishu, http, etc.)
    agent_name: str  # Configured agent name
    client: ACPClient  # ACP client instance
    cwd: str
    created_at: datetime = field(default_factory=datetime.now)
    last_active_at: datetime = field(default_factory=datetime.now)
    is_active: bool = False


class ACPSessionManager:
    """Manage ACP sessions with LRU-style eviction and idle cleanup."""

    def __init__(
        self,
        agents: dict[str, ACPAgentConfig],
        permission_policy: ACPPermissionPolicy,
        idle_timeout: int = 3600,
    ):
        self._agents = agents
        self._permission_policy = permission_policy
        self._idle_timeout = idle_timeout
        self._sessions: dict[str, ACPSession] = {}  # key = channel:chat_id:agent_name
        self._cleanup_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the idle-cleanup background task."""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self) -> None:
        """Stop all sessions and the cleanup task."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        for key, session in list(self._sessions.items()):
            await self._destroy_session(session)
        self._sessions.clear()

    async def get_or_create(
        self,
        chat_id: str,
        channel: str,
        agent_name: str,
    ) -> ACPSession:
        """Get an existing session or create a new one (spawns subprocess)."""
        key = f"{channel}:{chat_id}:{agent_name}"
        session = self._sessions.get(key)
        if session and session.client.is_alive:
            session.last_active_at = datetime.now()
            return session
        # Destroy stale session if any.
        if session:
            await self._destroy_session(session)

        agent_cfg = self._agents.get(agent_name)
        if not agent_cfg:
            raise ValueError(f"ACP agent '{agent_name}' not configured")

        # Build permission resolver.
        resolver = PermissionResolver(
            auto_approve_kinds=self._permission_policy.auto_approve_kinds,
            allow_paths=self._permission_policy.allow_paths,
            interactive=self._permission_policy.interactive,
        )

        client = ACPClient(permission_resolver=resolver, timeout=agent_cfg.timeout)
        await client.start(
            command=agent_cfg.command,
            args=agent_cfg.args,
            env=agent_cfg.env or None,
            cwd=agent_cfg.cwd,
        )
        await client.initialize()
        cwd = agent_cfg.cwd or "."
        acp_session_id = await client.create_session(cwd=cwd)

        session = ACPSession(
            session_id=acp_session_id,
            chat_id=chat_id,
            channel=channel,
            agent_name=agent_name,
            client=client,
            cwd=cwd,
        )
        self._sessions[key] = session
        logger.info(
            "ACP: created session for {}/{} → agent '{}' (sid={})",
            channel, chat_id, agent_name, acp_session_id[:8],
        )
        return session

    def resolve_agent_name(self, channel: str, chat_id: str, routing: dict[str, str], default: str | None) -> str | None:
        """Resolve which agent to use for a given chat."""
        # Try exact match first.
        exact = f"{channel}:{chat_id}"
        if exact in routing:
            return routing[exact]
        # Try wildcard pattern.
        pattern = f"{channel}:*"
        if pattern in routing:
            return routing[pattern]
        return default

    async def _destroy_session(self, session: ACPSession) -> None:
        """Tear down a session and kill its subprocess."""
        try:
            await session.client.shutdown()
        except Exception as exc:
            logger.warning("ACP: error shutting down session: {}", exc)

    async def _cleanup_loop(self) -> None:
        """Periodically clean up idle sessions."""
        try:
            while True:
                await asyncio.sleep(60)
                now = datetime.now()
                stale_keys = []
                for key, session in self._sessions.items():
                    if not session.is_active:
                        age = (now - session.last_active_at).total_seconds()
                        if age > self._idle_timeout:
                            stale_keys.append(key)
                for key in stale_keys:
                    session = self._sessions.pop(key, None)
                    if session:
                        logger.info("ACP: cleaning up idle session for {}", key)
                        await self._destroy_session(session)
        except asyncio.CancelledError:
            pass
