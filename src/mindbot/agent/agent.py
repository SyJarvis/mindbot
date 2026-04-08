"""Base Agent – a self-contained conversational agent.

Provides the core execution capabilities:
- Multi-turn conversation with per-session context management (LRU-evicted)
- Tool registration and execution via TurnEngine
- Streaming and non-streaming response modes
- Optional memory integration
- Configurable session cache size

Used directly for standalone agents, or composed into MindAgent for
supervisor / multi-agent scenarios.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mindbot.agent.input_builder import InputBuilder
from mindbot.agent.models import AgentEvent, AgentResponse, StopReason
from mindbot.agent.persistence_writer import PersistenceWriter, ToolPersistence
from mindbot.agent.turn_engine import TurnEngine
from mindbot.capability.backends.tooling import ToolRegistry
from mindbot.capability.backends.tooling.models import Tool
from mindbot.config.schema import ContextConfig
from mindbot.context import ContextManager
from mindbot.providers.adapter import ProviderAdapter
from mindbot.utils import get_logger

if TYPE_CHECKING:
    from mindbot.capability.backends.tool_backend import ToolBackend
    from mindbot.capability.backends.tooling.models import Tool as StaticTool
    from mindbot.capability.facade import CapabilityFacade, ScopedCapabilityFacade
    from mindbot.config.schema import SkillsConfig
    from mindbot.generation.dynamic_manager import DynamicToolManager
    from mindbot.memory.manager import MemoryManager
    from mindbot.session.store import SessionJournal
    from mindbot.skills.registry import SkillRegistry

logger = get_logger("agent")


def _capability_to_llm_tool(capability: Any) -> Tool:
    """Convert a capability back into a provider-bindable Tool proxy."""
    return Tool(
        name=capability.name,
        description=capability.description,
        parameters_schema_override=capability.parameters_schema,
        handler=None,
    )


def _normalize_registered_tool(tool: Any) -> Any:
    """Adapt legacy tool-like objects to the current Tool model."""
    if hasattr(tool, "parameters_json_schema"):
        return tool

    name = getattr(tool, "name", type(tool).__name__)
    description = getattr(tool, "description", "")
    parameters = getattr(tool, "parameters", None)
    handler = getattr(tool, "handler", None)
    if not callable(handler):
        handler = getattr(tool, "run", None)
    if not callable(handler):
        handler = getattr(tool, "execute", None)

    schema_override = parameters if isinstance(parameters, dict) else None
    return Tool(
        name=name,
        description=description,
        parameters_schema_override=schema_override,
        handler=handler,
    )


@dataclass(frozen=True)
class _TurnExecutionContext:
    """Runtime resources derived for one chat turn."""

    tools: list["StaticTool"]
    capability_facade: "CapabilityFacade | ScopedCapabilityFacade | None"
    tools_override_active: bool


class Agent:
    """A self-contained conversational agent.

    Each Agent instance manages:
    * An LLM provider (via ProviderAdapter).
    * A tool registry (populated via :meth:`register_tool`).
    * Per-session context and TurnEngine instances (LRU-evicted at
      ``max_sessions`` to bound memory usage).
    * Optional memory integration (retrieval + persistence).

    Agents are composed inside :class:`~mindbot.agent.core.MindAgent` for
    supervisor/multi-agent scenarios, but can also be used standalone.
    """

    def __init__(
        self,
        name: str,
        llm: ProviderAdapter,
        tools: list[Tool] | None = None,
        system_prompt: str = "",
        context_config: ContextConfig | None = None,
        memory: "MemoryManager | None" = None,
        memory_top_k: int = 5,
        tool_persistence: ToolPersistence = "none",
        max_iterations: int = 20,
        max_sessions: int = 1000,
        capability_facade: "CapabilityFacade | None" = None,
        tool_backend: "ToolBackend | None" = None,
        dynamic_manager: "DynamicToolManager | None" = None,
        skill_registry: "SkillRegistry | None" = None,
        skills_config: "SkillsConfig | None" = None,
    ) -> None:
        self.name = name
        self.llm = llm
        self.system_prompt = system_prompt
        self.memory = memory
        self._memory_top_k = memory_top_k
        self._tool_persistence = tool_persistence
        self._max_iterations = max_iterations
        self._max_sessions = max_sessions
        self._context_config = context_config or ContextConfig()
        self._capability_facade = capability_facade
        self._tool_backend = tool_backend
        self._dynamic_manager = dynamic_manager
        self._skill_registry = skill_registry
        self._skills_config = skills_config

        # Tool registry – pre-populate from constructor args
        self.tool_registry = ToolRegistry()
        for tool in (tools or []):
            self.tool_registry.register(_normalize_registered_tool(tool))

        # Session-keyed caches (LRU via OrderedDict)
        self._sessions: OrderedDict[str, ContextManager] = OrderedDict()
        self._turn_engines: OrderedDict[str, TurnEngine] = OrderedDict()
        # frozenset[tuple[name, id]] – detects same-name tool replacement
        self._turn_engine_tool_signatures: dict[
            str,
            tuple[bool, frozenset[tuple[str, int]]],
        ] = {}
        self._capability_tool_cache: dict[str, Tool] = {}
        self._journal: "SessionJournal | None" = None
        self._journal_sessions: set[str] = set()

    # ------------------------------------------------------------------
    # Tool management
    # ------------------------------------------------------------------

    def register_tool(self, tool: Any) -> None:
        """Register *tool* with this agent."""
        normalized = _normalize_registered_tool(tool)
        self.tool_registry.register(normalized)
        if self._tool_backend is not None:
            self._tool_backend.register_static(normalized, replace=True)
        if self._capability_facade is not None:
            self.refresh_capabilities()
        logger.debug(
            "Registered tool: %s",
            normalized.name if hasattr(normalized, "name") else type(normalized).__name__,
        )

    def list_tools(self) -> list[Any]:
        """Return all registered tools."""
        if self._capability_facade is not None:
            visible: list[Tool] = []
            live_ids: set[str] = set()
            for cap in self._capability_facade.list_capabilities():
                live_ids.add(cap.id)
                cached = self._capability_tool_cache.get(cap.id)
                if (
                    cached is None
                    or cached.name != cap.name
                    or cached.description != cap.description
                    or cached.parameters_schema_override != cap.parameters_schema
                ):
                    cached = _capability_to_llm_tool(cap)
                    self._capability_tool_cache[cap.id] = cached
                visible.append(cached)
            stale_ids = [cap_id for cap_id in self._capability_tool_cache if cap_id not in live_ids]
            for cap_id in stale_ids:
                del self._capability_tool_cache[cap_id]
            return visible
        return self.tool_registry.list_tools()

    def refresh_capabilities(self) -> None:
        """Refresh capability-backed tools and invalidate cached orchestrators."""
        if self._capability_facade is not None:
            self._capability_facade.refresh_registry()
        self._capability_tool_cache.clear()
        self._turn_engines.clear()
        self._turn_engine_tool_signatures.clear()

    async def reload_tools(self) -> int:
        """Reload persisted dynamic tools and refresh the capability view."""
        if self._dynamic_manager is None:
            self.refresh_capabilities()
            return len(self.list_tools())
        loaded = await self._dynamic_manager.reload_tools()
        self.refresh_capabilities()
        return loaded

    def get_tool_count(self) -> int:
        """Return the current visible tool count."""
        return len(self.list_tools())

    def has_tool(self, tool_name: str) -> bool:
        """Return whether a tool is currently visible to the LLM."""
        return any(getattr(tool, "name", None) == tool_name for tool in self.list_tools())

    def set_session_journal(self, journal: "SessionJournal | None") -> None:
        """Attach or detach the shared session journal for this agent."""
        self._journal = journal
        if journal is None:
            self._journal_sessions.clear()

    # ------------------------------------------------------------------
    # Session management (LRU)
    # ------------------------------------------------------------------

    def _get_session_context(self, session_id: str) -> ContextManager:
        """Return the ContextManager for *session_id*, creating it if needed.

        Uses LRU eviction: the least-recently-used session is dropped once the
        cache reaches ``_max_sessions``.
        """
        if session_id in self._sessions:
            self._sessions.move_to_end(session_id)
            return self._sessions[session_id]

        ctx = ContextManager(self._context_config)
        self._sessions[session_id] = ctx

        if len(self._sessions) > self._max_sessions:
            evicted = next(iter(self._sessions))
            self._sessions.pop(evicted)
            self._turn_engines.pop(evicted, None)
            self._turn_engine_tool_signatures.pop(evicted, None)
            logger.debug("Evicted session from LRU cache: %s", evicted)

        return ctx

    def _get_session_input_builder(self, session_id: str) -> InputBuilder:
        """Build an :class:`~mindbot.agent.input_builder.InputBuilder` for *session_id*."""
        context = self._get_session_context(session_id)
        return InputBuilder(
            context=context,
            memory=self.memory,
            memory_top_k=self._memory_top_k,
            system_prompt=self.system_prompt,
            skill_registry=self._skill_registry,
            skills_config=self._skills_config,
        )

    # ------------------------------------------------------------------
    # Tool signature (orchestrator cache invalidation)
    # ------------------------------------------------------------------

    def _get_tool_signature(self, tools: list[Any]) -> frozenset[tuple[str, int]]:
        """Return a signature that changes when tools are added or replaced.

        Includes the Python object identity (``id``) of each tool so that
        registering a new object under the same name is detected correctly.
        """
        sigs: set[tuple[str, int]] = set()
        for t in tools:
            name = t.name if hasattr(t, "name") else type(t).__name__
            sigs.add((name, id(t)))
        return frozenset(sigs)

    def _build_turn_context(
        self,
        tools: list[Any] | None,
    ) -> _TurnExecutionContext:
        """Build the tool/capability view used for one turn."""
        from mindbot.capability.facade import build_turn_scoped_facade

        tools_override_active = tools is not None
        if tools_override_active:
            effective_tools = [_normalize_registered_tool(tool) for tool in tools or []]
            capability_facade = build_turn_scoped_facade(
                self._capability_facade,
                effective_tools,
                override_tool_capabilities=True,
            )
        else:
            effective_tools = self.list_tools()
            if self._capability_facade is not None:
                capability_facade = self._capability_facade
            else:
                capability_facade = build_turn_scoped_facade(
                    None,
                    effective_tools,
                    override_tool_capabilities=False,
                )
        return _TurnExecutionContext(
            tools=effective_tools,
            capability_facade=capability_facade,
            tools_override_active=tools_override_active,
        )

    # ------------------------------------------------------------------
    # Orchestrator cache (per session)
    # ------------------------------------------------------------------

    def _get_turn_engine(
        self,
        session_id: str,
        turn_context: _TurnExecutionContext,
    ) -> TurnEngine:
        """Return the turn engine for *session_id*, rebuilding if tools changed."""
        tool_signature = (
            turn_context.tools_override_active,
            self._get_tool_signature(turn_context.tools),
        )
        cached_sig = self._turn_engine_tool_signatures.get(session_id)

        if session_id not in self._turn_engines or cached_sig != tool_signature:
            turn_engine = TurnEngine(
                llm=self.llm,
                tools=turn_context.tools,
                max_iterations=self._max_iterations,
                capability_facade=turn_context.capability_facade,
            )
            self._turn_engines[session_id] = turn_engine
            self._turn_engines.move_to_end(session_id)
            self._turn_engine_tool_signatures[session_id] = tool_signature
            logger.debug("Built turn engine for agent=%s session=%s", self.name, session_id)
        else:
            self._turn_engines.move_to_end(session_id)

        return self._turn_engines[session_id]

    def _get_persistence_writer(self, session_id: str) -> PersistenceWriter:
        """Build a :class:`PersistenceWriter` for *session_id*."""
        context = self._get_session_context(session_id)
        writer = PersistenceWriter(
            context=context,
            memory=self.memory,
            journal=self._journal,
            tool_persistence=self._tool_persistence,
            system_prompt=self.system_prompt,
        )
        writer._journal_sessions = self._journal_sessions
        return writer

    async def _run_turn(
        self,
        *,
        message: str,
        session_id: str,
        turn_context: _TurnExecutionContext,
        on_event: Callable[[AgentEvent], None] | None = None,
    ) -> AgentResponse:
        """Run one turn through the shared execution path."""
        input_builder = self._get_session_input_builder(session_id)
        messages = input_builder.build(message, session_id=session_id)
        turn_engine = self._get_turn_engine(session_id, turn_context)
        response = await turn_engine.run(
            messages=messages,
            on_event=on_event,
        )

        writer = self._get_persistence_writer(session_id)
        writer.commit_turn(message, response, session_id=session_id)
        return response

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
        """Non-streaming chat with tool support and memory integration.

        Args:
            message: User message text.
            session_id: Conversation identifier (creates a session on first use).
            on_event: Optional real-time event callback.
            tools: Per-call tool override.  When provided, completely replaces
                   the agent's registered tools for this turn.

        Returns:
            :class:`~mindbot.agent.models.AgentResponse`
        """
        turn_context = self._build_turn_context(tools)

        response = await self._run_turn(
            message=message,
            session_id=session_id,
            turn_context=turn_context,
            on_event=on_event,
        )

        logger.info(
            "chat: agent=%s session=%s stop_reason=%s",
            self.name,
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
        """Streaming chat.

        Streams token-by-token when no tools are active.  When tools are active
        the full turn runs first and the final content is yielded as a single
        chunk (tool calls require a complete response to parse).

        Yields:
            String chunks of the assistant response.
        """
        turn_context = self._build_turn_context(tools)
        response = await self._run_turn(
            message=message,
            session_id=session_id,
            turn_context=turn_context,
        )
        if response.content:
            yield response.content

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        tool_names = [t.name for t in self.list_tools()]
        return f"Agent(name={self.name!r}, tools={tool_names!r})"
