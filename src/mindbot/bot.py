"""MindBot - native implementation without Mindbot dependency."""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mindbot.agent.models import AgentEvent

from mindbot.config.schema import Config
from mindbot.config.loader import load_config
from mindbot.agent.core import MindAgent
from mindbot.cron.service import CronService


class MindBot:
    """MindBot - AI Assistant (Native Implementation).

    Usage::

        from mindbot import MindBot

        bot = MindBot()
        response = await bot.chat("Hello!")
        print(response.content)
    """

    def __init__(self, config: Config | None = None) -> None:
        """Initialize MindBot.

        Args:
            config: Config instance. If None, loads from ~/.mindbot/settings.yaml
                    and injects the system prompt from ~/.mindbot/SYSTEM.md.
        """
        if config is None:
            self.config = self._load_default_config()
        else:
            self.config = config

        self._inject_system_prompt()

        # Initialize agent
        self._agent = MindAgent(self.config)

        # Initialize Cron service
        cron_path = Path.home() / ".mindbot" / "cron" / "jobs.json"
        self.cron: CronService = CronService(cron_path)

        # State
        self._running = False

    @staticmethod
    def _load_default_config() -> Config:
        """Load default configuration from ~/.mindbot/settings.yaml.

        Returns:
            Config instance loaded from the default config file.

        Raises:
            SystemExit: If the config file doesn't exist. Prints a helpful
                        message directing the user to run 'mindbot generate-config'.
        """
        config_file = Path.home() / ".mindbot" / "settings.yaml"

        if not config_file.exists():
            print(
                f"[Error] Configuration file not found: {config_file}\n\n"
                "Please run the following command to initialize MindBot:\n"
                "  mindbot generate-config\n\n"
                "Then edit ~/.mindbot/settings.yaml to configure your providers.",
                file=sys.stderr,
            )
            sys.exit(1)

        return load_config(config_file)

    def _inject_system_prompt(self) -> None:
        """Read ``~/.mindbot/SYSTEM.md`` and set ``config.agent.system_prompt``.

        This is the **sole** source of the system prompt at runtime.
        """
        import logging

        logger = logging.getLogger("mindbot.bot")
        system_file = Path.home() / ".mindbot" / "SYSTEM.md"

        if not system_file.exists():
            print(
                f"[Error] System prompt file not found: {system_file}\n\n"
                "Please run the following command to initialize MindBot:\n"
                "  mindbot generate-config\n",
                file=sys.stderr,
            )
            sys.exit(1)

        content = system_file.read_text(encoding="utf-8").strip()
        if not content:
            logger.warning("SYSTEM.md is empty — MindBot will run without a system prompt")

        self.config.agent.system_prompt = content

    @classmethod
    def from_config(cls, config: Config) -> "MindBot":
        """Create Bot from config instance."""
        return cls(config)

    @classmethod
    def from_file(cls, path: str | None = None) -> "MindBot":
        """Create Bot from config file."""
        if path:
            config = load_config(path)
        else:
            config = Config.from_env()
        return cls(config)

    # ==================================================================
    # Properties
    # ==================================================================

    @property
    def model(self) -> str:
        """Current model."""
        return self.config.agent.model

    @property
    def provider(self) -> str:
        """Current provider."""
        return self.model.split("/")[0] if "/" in self.model else "unknown"

    @property
    def greeting(self) -> str:
        """Greeting message."""
        return "你好！我是 MindBot，有什么可以帮你的吗？"

    # ==================================================================
    # Chat Interfaces
    # ==================================================================

    async def chat(
        self,
        message: str,
        session_id: str = "default",
        tools: list[Any] | None = None,
        on_event: "Callable[[AgentEvent], None] | None" = None,
    ) -> Any:
        """Primary async chat entry point.

        Args:
            message: User message
            session_id: Session identifier for conversation context
            tools: Tools available for this turn.  When provided, completely
                   overrides tools registered via register_tool().  When None,
                   falls back to the registered tool registry.
            on_event: Optional callback invoked for each :class:`~mindbot.agent.models.AgentEvent`
                      emitted during the turn (e.g. tool calls, streaming deltas, completion).

        Returns:
            :class:`~mindbot.agent.models.AgentResponse` with content,
            events, and stop_reason.  Use ``response.content`` for the
            plain-text reply.
        """
        return await self._agent.chat(
            message,
            session_id=session_id,
            tools=tools,
            on_event=on_event,
        )

    async def chat_stream(
        self,
        message: str,
        session_id: str = "default",
        tools: list[Any] | None = None,
    ) -> AsyncIterator[str]:
        """Primary async streaming chat entry point.

        Streams token-by-token when no tools are active.  When tools are
        active the full turn runs first and the final content is yielded as
        a single chunk.

        Args:
            message: User message
            session_id: Session identifier for conversation context
            tools: Tools available for this turn (overrides registry when set).

        Yields:
            String chunks of the assistant response
        """
        async for chunk in self._agent.chat_stream(message, session_id=session_id, tools=tools):
            yield chunk

    # ------------------------------------------------------------------
    # Deprecated compatibility shims – kept for one release cycle
    # ------------------------------------------------------------------

    async def chat_async(
        self,
        message: str,
        session_id: str = "default",
        tools: list[Any] | None = None,
    ) -> str:
        """Deprecated: use chat() instead.

        .. deprecated::
            Use :meth:`chat` which returns the full
            :class:`~mindbot.agent.models.AgentResponse`.
        """
        import warnings
        warnings.warn(
            "chat_async() is deprecated; use chat() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        response = await self.chat(message, session_id=session_id, tools=tools)
        return response.content

    async def chat_stream_async(
        self,
        message: str,
        session_id: str = "default",
    ) -> AsyncIterator[str]:
        """Deprecated: use chat_stream() instead.

        .. deprecated::
            Use :meth:`chat_stream` which also accepts a *tools* parameter.
        """
        import warnings
        warnings.warn(
            "chat_stream_async() is deprecated; use chat_stream() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        async for chunk in self.chat_stream(message, session_id=session_id):
            yield chunk

    async def chat_with_agent_async(
        self,
        message: str,
        agent_name: str = "default",
        tools: list[Any] | None = None,
    ) -> Any:
        """Deprecated: use chat() with the *tools* parameter instead.

        .. deprecated::
            Use :meth:`chat` and pass tools via the *tools* keyword argument.
        """
        import warnings
        warnings.warn(
            "chat_with_agent_async() is deprecated; use chat() with tools= instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return await self.chat(message, session_id=agent_name, tools=tools)

    # ==================================================================
    # Memory Interfaces
    # ==================================================================

    def add_to_memory(self, content: str, permanent: bool = False) -> None:
        """Add to memory."""
        self._agent.add_to_memory(content, permanent)

    def search_memory(self, query: str, top_k: int = 5) -> list[Any]:
        """Search memory."""
        return self._agent.search_memory(query, top_k)

    # ==================================================================
    # Tool Interfaces
    # ==================================================================

    def register_tool(self, tool: Any) -> None:
        """Register tool."""
        self._agent.register_tool(tool)

    def list_tools(self) -> list[Any]:
        """List tools."""
        return self._agent.list_tools()

    # ==================================================================
    # Introspection
    # ==================================================================

    def get_llm_info(self) -> Any:
        """Get LLM info."""
        from mindbot.context.models import ProviderInfo
        return ProviderInfo(
            provider=self.provider,
            model=self.model,
            supports_vision=False,
            supports_tools=True,
        )

    @property
    def is_running(self) -> bool:
        """Check if running."""
        return self._running

    async def start(self) -> None:
        """Start bot and cron."""
        self._running = True
        await self.cron.start()

    async def stop(self) -> None:
        """Stop bot and cron."""
        self._running = False
        await self.cron.stop()
