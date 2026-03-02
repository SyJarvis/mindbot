"""Base Agent – a self-contained conversational agent.

Provides the core execution capabilities:
- Multi-turn conversation with per-session context management (LRU-evicted)
- Tool registration, approval, and execution via AgentOrchestrator
- Streaming and non-streaming response modes
- Optional memory integration
- Configurable session cache size

Used directly for standalone agents, or composed into MindAgent for
supervisor / multi-agent scenarios.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING, Any

from mindbot.agent.interrupt import AgentExecution
from mindbot.agent.models import AgentEvent, AgentResponse, StopReason
from mindbot.agent.orchestrator import AgentOrchestrator
from mindbot.agent.scheduler import Scheduler
from mindbot.capability.backends.tooling import ToolRegistry
from mindbot.capability.backends.tooling.models import Tool
from mindbot.config.schema import ContextConfig, ToolApprovalConfig
from mindbot.context import ContextManager
from mindbot.providers.adapter import ProviderAdapter
from mindbot.utils import get_logger

if TYPE_CHECKING:
    from mindbot.capability.facade import CapabilityFacade
    from mindbot.memory.manager import MemoryManager

logger = get_logger("agent")


class Agent:
    """A self-contained conversational agent.

    Each Agent instance manages:
    * An LLM provider (via ProviderAdapter).
    * A tool registry (populated via :meth:`register_tool`).
    * Per-session context and orchestrator instances (LRU-evicted at
      ``max_sessions`` to bound memory usage).
    * An approval configuration that gates tool execution.
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
        approval_config: ToolApprovalConfig | None = None,
        context_config: ContextConfig | None = None,
        memory: "MemoryManager | None" = None,
        memory_top_k: int = 5,
        max_iterations: int = 20,
        max_sessions: int = 1000,
        capability_facade: "CapabilityFacade | None" = None,
    ) -> None:
        self.name = name
        self.llm = llm
        self.system_prompt = system_prompt
        self.memory = memory
        self._memory_top_k = memory_top_k
        self._max_iterations = max_iterations
        self._max_sessions = max_sessions
        self._context_config = context_config or ContextConfig()
        # Phase 1: stored for propagation to orchestrators; not yet wired.
        self._capability_facade = capability_facade

        # Tool registry – pre-populate from constructor args
        self.tool_registry = ToolRegistry()
        for tool in (tools or []):
            self.tool_registry.register(tool)

        # Approval configuration
        self._approval_config = approval_config or ToolApprovalConfig()

        # Session-keyed caches (LRU via OrderedDict)
        self._sessions: OrderedDict[str, ContextManager] = OrderedDict()
        self._orchestrators: OrderedDict[str, AgentOrchestrator] = OrderedDict()
        # frozenset[tuple[name, id]] – detects same-name tool replacement
        self._orchestrator_tool_signatures: dict[str, frozenset[tuple[str, int]]] = {}

    # ------------------------------------------------------------------
    # Tool management
    # ------------------------------------------------------------------

    def register_tool(self, tool: Any) -> None:
        """Register *tool* with this agent."""
        self.tool_registry.register(tool)
        logger.debug(
            "Registered tool: %s",
            tool.name if hasattr(tool, "name") else type(tool).__name__,
        )

    def list_tools(self) -> list[Any]:
        """Return all registered tools."""
        return self.tool_registry.list_tools()

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
            self._orchestrators.pop(evicted, None)
            self._orchestrator_tool_signatures.pop(evicted, None)
            logger.debug("Evicted session from LRU cache: %s", evicted)

        return ctx

    def _get_session_scheduler(self, session_id: str) -> Scheduler:
        """Build a :class:`~mindbot.agent.scheduler.Scheduler` for *session_id*."""
        context = self._get_session_context(session_id)
        return Scheduler(
            context=context,
            memory=self.memory,
            tool_registry=self.tool_registry,
            memory_top_k=self._memory_top_k,
            system_prompt=self.system_prompt,
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

    # ------------------------------------------------------------------
    # Orchestrator cache (per session)
    # ------------------------------------------------------------------

    def _get_orchestrator(
        self,
        session_id: str,
        effective_tools: list[Any],
    ) -> AgentOrchestrator:
        """Return the orchestrator for *session_id*, rebuilding if tools changed."""
        tool_signature = self._get_tool_signature(effective_tools)
        cached_sig = self._orchestrator_tool_signatures.get(session_id)

        if session_id not in self._orchestrators or cached_sig != tool_signature:
            orchestrator = AgentOrchestrator(
                llm=self.llm,
                tools=effective_tools,
                approval_config=self._approval_config,
                max_iterations=self._max_iterations,
                capability_facade=self._capability_facade,
            )
            self._orchestrators[session_id] = orchestrator
            self._orchestrators.move_to_end(session_id)
            self._orchestrator_tool_signatures[session_id] = tool_signature
            logger.debug("Built orchestrator for agent=%s session=%s", self.name, session_id)
        else:
            self._orchestrators.move_to_end(session_id)

        return self._orchestrators[session_id]

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
        effective_tools = tools if tools is not None else self.tool_registry.list_tools()

        # Per-call tool overrides are always auto-approved
        if tools is not None:
            for t in effective_tools:
                name = t.name if hasattr(t, "name") else type(t).__name__
                self._approval_config.add_to_whitelist(name, pattern=".*")

        scheduler = self._get_session_scheduler(session_id)
        messages = scheduler.assemble(message, session_id=session_id)
        orchestrator = self._get_orchestrator(session_id, effective_tools)
        execution = AgentExecution()

        response = await orchestrator.chat(
            messages=messages,
            on_event=on_event,
            execution=execution,
        )

        assistant_text = response.content or ""
        scheduler.commit(message, assistant_text)
        scheduler.save_to_memory(message, assistant_text)

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
        effective_tools = tools if tools is not None else self.tool_registry.list_tools()

        if not effective_tools:
            scheduler = self._get_session_scheduler(session_id)
            messages = scheduler.assemble(message, session_id=session_id)

            full_content = ""
            async for chunk in self.llm.chat_stream(messages):
                full_content += chunk
                yield chunk

            scheduler.commit(message, full_content)
            scheduler.save_to_memory(message, full_content)
        else:
            response = await self.chat(message=message, session_id=session_id, tools=tools)
            if response.content:
                yield response.content

    # ------------------------------------------------------------------
    # Approval & input forwarding
    # ------------------------------------------------------------------

    def resolve_approval(
        self,
        request_id: str,
        decision: str,
        session_id: str = "default",
    ) -> None:
        """Resolve a pending tool approval request for *session_id*."""
        orchestrator = self._orchestrators.get(session_id)
        if orchestrator:
            orchestrator.resolve_approval(request_id, decision)

    def provide_input(
        self,
        request_id: str,
        input_text: str,
        session_id: str = "default",
    ) -> None:
        """Provide input for a pending user-input request."""
        orchestrator = self._orchestrators.get(session_id)
        if orchestrator:
            orchestrator.provide_input(request_id, input_text)

    def add_tool_to_whitelist(
        self,
        tool_name: str,
        pattern: str = ".*",
        session_id: str | None = None,
    ) -> None:
        """Add *tool_name* to the approval whitelist.

        When *session_id* is given the live orchestrator for that session is
        also updated; otherwise only the shared approval_config is changed
        (takes effect on the next orchestrator rebuild for each session).
        """
        self._approval_config.add_to_whitelist(tool_name, pattern)
        if session_id:
            orchestrator = self._orchestrators.get(session_id)
            if orchestrator:
                orchestrator.add_tool_to_whitelist(tool_name, pattern)

    def remove_tool_from_whitelist(
        self,
        tool_name: str,
        session_id: str | None = None,
    ) -> None:
        """Remove *tool_name* from the approval whitelist."""
        self._approval_config.remove_from_whitelist(tool_name)
        if session_id:
            orchestrator = self._orchestrators.get(session_id)
            if orchestrator:
                orchestrator.remove_tool_from_whitelist(tool_name)

    @property
    def approval_config(self) -> ToolApprovalConfig:
        """The approval configuration for this agent."""
        return self._approval_config

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        tool_names = [t.name for t in self.tool_registry.list_tools()]
        return f"Agent(name={self.name!r}, tools={tool_names!r})"
