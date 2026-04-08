"""MindBot supervisor agent – primary user-facing entry point.

MindAgent acts as a Supervisor that:
* Creates and owns a *main Agent* which handles conversation, tools, and memory.
* Maintains a registry of named *child Agents* for sub-task delegation.
* Wires an optional append-only Session Journal into the shared persistence path.
* Keeps the same public API as before, so existing channels (CLI, HTTP,
  Feishu …) and the MindBot wrapper do not need changes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING, Any

from mindbot.agent.agent import Agent
from mindbot.agent.models import AgentEvent, AgentResponse, StopReason, TurnResult
from mindbot.builders import create_agent, create_llm
from mindbot.capability.backends.tooling import ToolRegistry
from mindbot.config.schema import Config
from mindbot.memory import MemoryManager
from mindbot.session import SessionJournal
from mindbot.utils import get_logger

if TYPE_CHECKING:
    from mindbot.capability.facade import CapabilityFacade

logger = get_logger("agent.core")


class MindAgent:
    """MindBot supervisor agent.

    Provides:
    - Single-turn and multi-turn conversations (delegated to main Agent)
    - Tool calling support (delegated to main Agent)
    - Memory integration (delegated to main Agent)
    - Child agent registry for sub-task delegation
    - Optional session journal persistence
    - MessageBus integration for channel communication
    """

    def __init__(
        self,
        config: Config,
        capability_facade: "CapabilityFacade | None" = None,
    ) -> None:
        """Initialise the supervisor.

        Args:
            config: Root configuration.
            capability_facade: Optional CapabilityFacade for Phase 2+
                capability-layer execution.
        """
        self.config = config
        self._capability_facade = capability_facade

        # Build the main agent from config
        self._main_agent: Agent = self._build_main_agent(config, capability_facade)

        # Child agent registry (name → Agent)
        self._child_agents: dict[str, Agent] = {}

        # Session Journal (append-only per-session message persistence)
        self._journal: SessionJournal | None = None
        if config.session_journal.enabled:
            self._journal = SessionJournal(config.session_journal.path)
            logger.info("Session journal enabled at %s", config.session_journal.path)
        self._main_agent.set_session_journal(self._journal)

    # ------------------------------------------------------------------
    # Internal factory
    # ------------------------------------------------------------------

    def _build_main_agent(
        self,
        config: Config,
        capability_facade: "CapabilityFacade | None",
    ) -> Agent:
        """Construct the main Agent from configuration via the builder layer."""
        llm = create_llm(config)
        mode = "routing" if config.routing.auto else "single-provider"
        logger.info("MindAgent: main agent uses %s mode", mode)

        return create_agent(
            config,
            llm=llm,
            name="main",
            capability_facade=capability_facade,
        )

    # ------------------------------------------------------------------
    # Accessors (forwarded from main agent)
    # ------------------------------------------------------------------

    @property
    def llm(self) -> Any:
        """The LLM adapter used by the main agent."""
        return self._main_agent.llm

    @property
    def memory(self) -> MemoryManager:
        """The memory manager used by the main agent."""
        return self._main_agent.memory

    @property
    def tool_registry(self) -> ToolRegistry:
        """The tool registry of the main agent."""
        return self._main_agent.tool_registry

    # ------------------------------------------------------------------
    # Child agent management
    # ------------------------------------------------------------------

    def register_child_agent(self, agent: Agent) -> None:
        """Register *agent* as a child agent under its name."""
        self._child_agents[agent.name] = agent
        logger.info("Registered child agent: %s", agent.name)

    def get_child_agent(self, name: str) -> Agent | None:
        """Return the child agent registered under *name*, or None."""
        return self._child_agents.get(name)

    def list_child_agents(self) -> list[Agent]:
        """Return all registered child agents."""
        return list(self._child_agents.values())

    # ------------------------------------------------------------------
    # Tool management (delegated to main agent)
    # ------------------------------------------------------------------

    def register_tool(self, tool: Any) -> None:
        """Register a tool with the main agent."""
        self._main_agent.register_tool(tool)

    def list_tools(self) -> list[Any]:
        """List tools registered with the main agent."""
        return self._main_agent.list_tools()

    def refresh_capabilities(self) -> None:
        """Refresh capabilities on the main agent and all child agents."""
        self._main_agent.refresh_capabilities()
        for child in self._child_agents.values():
            child.refresh_capabilities()

    async def reload_tools(self) -> int:
        """Reload persisted tools on the main agent and refresh all agents."""
        loaded = await self._main_agent.reload_tools()
        for child in self._child_agents.values():
            child.refresh_capabilities()
        return loaded

    def get_tool_count(self) -> int:
        """Return the current visible tool count."""
        return self._main_agent.get_tool_count()

    def has_tool(self, tool_name: str) -> bool:
        """Return whether the main agent currently exposes *tool_name*."""
        return self._main_agent.has_tool(tool_name)

    # ------------------------------------------------------------------
    # Chat interfaces
    # ------------------------------------------------------------------

    async def chat(
        self,
        message: str,
        session_id: str = "default",
        on_event: Callable[[AgentEvent], None] | None = None,
        tools: list[Any] | None = None,
    ) -> AgentResponse:
        """Primary async chat entry point.

        Delegates execution to the main Agent, which persists the full turn.

        Args:
            message: User message.
            session_id: Session identifier.
            on_event: Optional real-time event callback.
            tools: Per-call tool override.

        Returns:
            :class:`~mindbot.agent.models.AgentResponse`
        """
        response = await self._main_agent.chat(
            message=message,
            session_id=session_id,
            on_event=on_event,
            tools=tools,
        )

        logger.info(
            "chat: session=%s stop_reason=%s",
            session_id,
            response.stop_reason,
        )
        return response

    async def chat_stream(
        self,
        message: str,
        session_id: str = "default",
        tools: list[Any] | None = None,
    ) -> AsyncIterator[str]:
        """Primary async streaming chat entry point.

        Delegates to the main Agent, which persists the full turn before the
        final response chunks are yielded.

        Yields:
            String chunks of the assistant response.
        """
        async for chunk in self._main_agent.chat_stream(
            message=message,
            session_id=session_id,
            tools=tools,
        ):
            yield chunk

    # ------------------------------------------------------------------
    # Memory interfaces
    # ------------------------------------------------------------------

    def add_to_memory(self, content: str, permanent: bool = False) -> None:
        """Add *content* to the main agent's memory."""
        if permanent:
            self._main_agent.memory.promote_to_long_term(content)
        else:
            self._main_agent.memory.append_to_short_term(content)

    def search_memory(self, query: str, top_k: int = 5) -> list[Any]:
        """Search the main agent's memory."""
        return self._main_agent.memory.search(query, top_k=top_k)

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
        response = await self.chat(message=message, session_id=session_id, tools=tools)
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
        async for chunk in self.chat_stream(message=message, session_id=session_id):
            yield chunk

    async def chat_with_tools_async(
        self,
        message: str,
        session_id: str = "default",
    ) -> TurnResult:
        """Deprecated: use chat() with the *tools* parameter instead."""
        import warnings
        warnings.warn(
            "chat_with_tools_async() is deprecated; use chat() with tools= instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        response = await self.chat(message=message, session_id=session_id)
        return TurnResult(
            final_response=response.content or "",
            steps=[],
            stop_reason=response.stop_reason,
        )
