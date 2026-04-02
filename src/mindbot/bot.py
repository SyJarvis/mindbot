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
from mindbot.config.store import ConfigStore
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

    def __init__(
        self,
        config: Config | None = None,
        *,
        config_store: ConfigStore | None = None,
    ) -> None:
        """Initialize MindBot.

        Args:
            config: Config instance. If None, loads from ~/.mindbot/settings.json
                    and injects the system prompt from ~/.mindbot/SYSTEM.md.
            config_store: Optional pre-built ConfigStore for hot-reload support.
        """
        if config_store is not None:
            self._store = config_store
            self.config = config_store.config
        elif config is not None:
            self.config = config
            self._store = None
        else:
            self.config = self._load_default_config()
            self._store = None

        self._inject_system_prompt()

        # Initialize agent
        self._agent = MindAgent(self.config)

        # Initialize Cron service
        cron_path = Path.home() / ".mindbot" / "cron" / "jobs.json"
        self.cron: CronService = CronService(cron_path)

        # State
        self._running = False

    @property
    def store(self) -> ConfigStore | None:
        """The ConfigStore (if hot-reload is active)."""
        return self._store

    @staticmethod
    def _load_default_config() -> Config:
        """Load default configuration from ~/.mindbot/settings.json.

        Returns:
            Config instance loaded from the default config file.

        Raises:
            SystemExit: If the config file doesn't exist.
        """
        root = Path.home() / ".mindbot"
        config_file = root / "settings.json"

        if not config_file.exists():
            print(
                f"[Error] Configuration file not found in {root}\n\n"
                "Please run the following command to initialize MindBot:\n"
                "  mindbot generate-config\n\n"
                "Then edit ~/.mindbot/settings.json to configure your providers.",
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
        """Current provider instance name."""
        return self.model.split("/")[0] if "/" in self.model else "unknown"

    @property
    def greeting(self) -> str:
        """Greeting message."""
        return "你好！我是 MindBot，有什么可以帮你的吗？"

    # ==================================================================
    # Runtime model switching
    # ==================================================================

    def list_available_models(self) -> list[str]:
        """Return all available models as ``instance/model`` strings.

        If routing is enabled, delegates to the router. Otherwise returns
        the single configured model.
        """
        if self.config.routing.auto:
            from mindbot.routing.router import ModelRouter
            return ModelRouter(self.config).get_model_list()
        return [self.config.agent.model]

    def set_model(self, model_ref: str) -> None:
        """Switch the active model at runtime.

        Args:
            model_ref: Model reference in ``instance/model`` format
                (e.g. ``"my-ollama/qwen3"``).

        Raises:
            ValueError: If the model_ref is invalid or the instance
                is not configured.
        """
        from mindbot.builders.model_ref import parse_model_ref

        instance_name, model_name = parse_model_ref(model_ref)

        provider_cfg = self.config.providers.get(instance_name)
        if provider_cfg is None:
            available = ", ".join(self.config.providers.keys()) or "(none)"
            raise ValueError(
                f"Provider instance '{instance_name}' not found. "
                f"Available: {available}"
            )

        # Update config
        self.config.agent.model = f"{instance_name}/{model_name}"

        # Rebuild the LLM adapter
        from mindbot.builders import create_llm
        new_llm = create_llm(self.config)
        self._agent._main_agent.llm = new_llm

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
        """Deprecated: use chat() instead."""
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
        """Deprecated: use chat_stream() instead."""
        import warnings
        warnings.warn(
            "chat_stream_async() is deprecated; use chat_stream() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        async for chunk in self.chat_stream(message, session_id=session_id):
            yield chunk

    def refresh_capabilities(self) -> None:
        """Refresh runtime-visible capabilities."""
        self._agent.refresh_capabilities()

    async def reload_tools(self) -> int:
        """Reload persisted tools and refresh the active capability graph."""
        return await self._agent.reload_tools()

    async def chat_with_agent_async(
        self,
        message: str,
        agent_name: str = "default",
        tools: list[Any] | None = None,
    ) -> Any:
        """Deprecated: use chat() with the *tools* parameter instead."""
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
        """Start bot, cron, and config watcher (if available)."""
        self._running = True
        await self.cron.start()
        if self._store is not None:
            await self._store.watch()

    async def stop(self) -> None:
        """Stop bot, cron, and config watcher."""
        self._running = False
        if self._store is not None:
            await self._store.stop_watch()
        await self.cron.stop()
