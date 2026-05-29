"""MindBot - native implementation without Mindbot dependency."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mindbot.agent.models import AgentEvent
    from mindbot.routing.health import HealthMonitor

from mindbot.config.schema import Config
from mindbot.config.loader import load_config
from mindbot.config.store import ConfigStore
from mindbot.agent.core import MindAgent
from mindbot.cron.service import CronService
from mindbot.logging import logger, setup_logging
from mindbot.runtime import ensure_runtime_home


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

        ensure_runtime_home(self.config)
        setup_logging(self.config.logging)

        self._inject_system_prompt()

        # Initialize agent (deferred: allow shell to start without valid LLM config)
        self._agent: MindAgent | None = None
        self._agent_error: str | None = None
        try:
            self._agent = MindAgent(self.config)
        except Exception as e:
            self._agent_error = str(e)
            logger.warning("Agent initialization deferred: {}", e)
            self._agent = None

        # Initialize Cron service
        cron_path = Path.home() / ".mindbot" / "cron" / "jobs.json"
        self.cron: CronService = CronService(cron_path, on_job=self._on_cron_job)

        # Initialize HealthMonitor if routing is enabled
        self._health_monitor: "HealthMonitor | None" = None
        if self._agent is not None and self.config.routing.auto and self.config.routing.health_probe.enabled:
            from mindbot.routing.health import HealthMonitor
            from mindbot.routing.health import HealthProbeConfig
            from mindbot.routing.adapter import RoutingProviderAdapter

            # Get the RoutingProviderAdapter's EndpointManager
            llm = self._agent._main_agent.llm
            if isinstance(llm, RoutingProviderAdapter):
                probe_config = HealthProbeConfig(
                    enabled=self.config.routing.health_probe.enabled,
                    probe_interval_seconds=self.config.routing.health_probe.probe_interval_seconds,
                    probe_timeout_seconds=self.config.routing.health_probe.probe_timeout_seconds,
                    success_threshold=self.config.routing.health_probe.success_threshold,
                )
                self._health_monitor = HealthMonitor(
                    self.config,
                    llm._endpoint_manager,
                    probe_config,
                )

        # Register cron tools with the agent
        self._register_cron_tools()

        # State
        self._running = False
        self._deliver_fn: Any | None = None  # async (channel, to, content) -> None
        self._channel_ctx: dict[str, str] = {}  # {"channel": "feishu", "to": "ou_xxx"}

    def set_delivery_callback(self, fn: Any) -> None:
        """Set a callback for delivering cron results to channels.

        Args:
            fn: async function(channel: str, to: str, content: str) -> None
        """
        self._deliver_fn = fn

    @property
    def store(self) -> ConfigStore | None:
        """The ConfigStore (if hot-reload is active)."""
        return self._store

    @staticmethod
    def _load_default_config() -> Config:
        """Load default configuration from ``~/.mindbot/settings.json``
        if it exists, otherwise load from the built-in defaults.
        """
        root = Path.home() / ".mindbot"
        config_file = root / "settings.json"

        if config_file.exists():
            return load_config(config_file)
        return load_config()

    def _inject_system_prompt(self) -> None:
        """Set ``config.agent.system_prompt`` from ``~/.mindbot/SYSTEM.md``
        if the user has created one, otherwise use the built-in default.

        This is the **sole** source of the system prompt at runtime.
        """
        system_file = Path.home() / ".mindbot" / "SYSTEM.md"

        if system_file.exists():
            content = system_file.read_text(encoding="utf-8").strip()
            self.config.agent.system_prompt = content
            return

        # No user SYSTEM.md — use built-in default
        try:
            from importlib import resources
            default_prompt = resources.files("mindbot.templates").joinpath("SYSTEM.md").read_text(encoding="utf-8").strip()
            self.config.agent.system_prompt = default_prompt
        except Exception:
            self.config.agent.system_prompt = ""

    def _require_agent(self) -> MindAgent:
        """Return the agent, raising a clear error if LLM config is missing."""
        if self._agent is not None:
            return self._agent
        msg = self._agent_error or "Agent not initialized"
        raise RuntimeError(f"LLM not available: {msg}\n"
                           "Configure ~/.mindbot/settings.json or set MIND_AGENT__MODEL")

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

    def list_tools(self) -> list[Any]:
        """Return the tools currently registered on the main agent."""
        if self._agent is None:
            return []
        return self._agent.list_tools()

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
        agent = self._require_agent()
        agent._main_agent.llm = new_llm

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
        agent = self._require_agent()
        return await agent.chat(
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
        agent = self._require_agent()
        async for chunk in agent.chat_stream(message, session_id=session_id, tools=tools):
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
        if self._agent is not None:
            self._agent.refresh_capabilities()

    async def reload_tools(self) -> int:
        """Reload persisted tools and refresh the active capability graph."""
        if self._agent is None:
            return 0
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
        if self._agent is not None:
            self._agent.add_to_memory(content, permanent)

    async def search_memory(self, query: str, top_k: int = 5) -> list[Any]:
        """Recall memory hits via the underlying agent.

        Returns a list of :class:`~mindbot.memory.types.MemoryHit` so
        callers can inspect retrieval signals; await is required because
        recall now runs the full hybrid retriever (vector + FTS + …).
        """
        if self._agent is None:
            return []
        return await self._agent.search_memory(query, top_k)

    # ==================================================================
    # Context Management Interfaces
    # ==================================================================

    def clear_context(self, session_id: str = "default") -> None:
        """Clear all context for a session."""
        if self._agent is not None:
            self._agent.clear_context(session_id)

    async def compact_context(self, session_id: str = "default") -> int:
        """Force compress the conversation block for a session.

        Returns:
            Token count after compaction.
        """
        if self._agent is None:
            return 0
        return await self._agent.compact_context(session_id)

    def get_conversation_token_count(self, session_id: str = "default") -> int:
        """Return the conversation block token count for a session."""
        if self._agent is None:
            return 0
        return self._agent.get_conversation_token_count(session_id)

    def list_sessions(self) -> list[str]:
        """List past session IDs from the journal."""
        if not self.config.session_journal.enabled:
            return []
        try:
            from mindbot.session.store import SessionJournal
            journal = SessionJournal(self.config.session_journal.path)
            return journal.list_sessions()
        except Exception:
            return []

    # ==================================================================
    # Tool Interfaces
    # ==================================================================

    def register_tool(self, tool: Any) -> None:
        """Register tool."""
        if self._agent is not None:
            self._agent.register_tool(tool)

    # ==================================================================
    # Cron
    # ==================================================================

    async def _on_cron_job(self, job: object) -> str | None:
        """Handle a fired cron job by sending its message to the agent."""
        if self._agent is None:
            return None
        try:
            response = await self._agent.chat(
                job.payload.message,
                session_id=f"cron-{job.id}",
            )
            # Deliver to channel if configured
            if job.payload.deliver and self._deliver_fn and response.content:
                try:
                    await self._deliver_fn(
                        channel=job.payload.channel or "feishu",
                        to=job.payload.to or "",
                        content=response.content,
                    )
                except Exception as exc:
                    logger.error("Cron deliver {} failed: {}", job.id, exc)
            return response.content
        except Exception as exc:
            logger.error("Cron job {} failed: {}", job.id, exc)
            return None

    def _register_cron_tools(self) -> None:
        """Create and register cron management tools on the agent."""
        if self._agent is None:
            return
        from mindbot.tools.cron_ops import create_cron_tools

        for tool in create_cron_tools(self.cron, channel_ctx_fn=lambda: self._channel_ctx):
            self._agent.register_tool(tool)

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
        """Start bot, cron, health monitor, and config watcher (if available)."""
        self._running = True
        await self.cron.start()
        if self._health_monitor is not None:
            await self._health_monitor.start()
        if self._store is not None:
            await self._store.watch()

    async def stop(self) -> None:
        """Stop bot, health monitor, cron, and config watcher."""
        self._running = False
        if self._store is not None:
            await self._store.stop_watch()
        if self._health_monitor is not None:
            await self._health_monitor.stop()
        await self.cron.stop()

    def get_health_status(self) -> dict[str, Any]:
        """Get comprehensive health status for all providers.

        Returns:
            Dict mapping endpoint keys to health status info.
            Includes is_healthy, failures, last_probe_time, etc.
        """
        if self._health_monitor is not None:
            return self._health_monitor.get_health_status()
        # Single-provider mode - no health monitoring
        return {
            "default": {
                "instance": self.provider,
                "model": self.model,
                "is_healthy": True,
                "status": "active",
            }
        }
