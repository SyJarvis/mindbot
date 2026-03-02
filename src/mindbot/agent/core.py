"""MindBot supervisor agent – primary user-facing entry point.

MindAgent acts as a Supervisor that:
* Creates and owns a *main Agent* which handles conversation, tools, and memory.
* Maintains a registry of named *child Agents* for sub-task delegation.
* Exposes a unified approval / input gateway so callers never need to know
  which underlying agent handles a particular session.
* Writes an optional append-only Session Journal after each turn.
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
from mindbot.config.schema import Config, ToolApprovalConfig
from mindbot.context.models import Message
from mindbot.memory import MemoryManager
from mindbot.session import SessionJournal
from mindbot.session.types import SessionMessage
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
    - Unified approval / input entry point across all managed agents
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
        self._journal_sessions: set[str] = set()

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

    @property
    def approval_config(self) -> ToolApprovalConfig:
        """The approval configuration of the main agent."""
        return self._main_agent.approval_config

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

    # ------------------------------------------------------------------
    # Session Journal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _msgs_to_journal(msgs: list[Message]) -> list[SessionMessage]:
        result: list[SessionMessage] = []
        for m in msgs:
            tool_calls = None
            if m.tool_calls:
                tool_calls = [
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                    for tc in m.tool_calls
                ]
            result.append(SessionMessage(
                role=m.role,
                content=m.text,
                timestamp=m.timestamp,
                tool_calls=tool_calls,
                tool_call_id=m.tool_call_id,
                reasoning_content=m.reasoning_content,
            ))
        return result

    def _write_journal(
        self,
        session_id: str,
        user_message: str,
        assistant_content: str,
        trace: list[Message] | None = None,
    ) -> None:
        """Persist the current turn to the journal (if enabled)."""
        if self._journal is None:
            return

        entries: list[SessionMessage] = []

        if session_id not in self._journal_sessions:
            system_prompt = self.config.agent.system_prompt
            if system_prompt:
                entries.append(SessionMessage(role="system", content=system_prompt))
            self._journal_sessions.add(session_id)

        entries.append(SessionMessage(role="user", content=user_message))

        if trace:
            entries.extend(self._msgs_to_journal(trace))

        entries.append(SessionMessage(role="assistant", content=assistant_content))
        self._journal.append(session_id, entries)

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

        Delegates execution to the main Agent, then writes the session journal.

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

        self._write_journal(
            session_id,
            user_message=message,
            assistant_content=response.content or "",
            trace=response.message_trace or None,
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

        Delegates to the main Agent and writes the journal after the stream
        completes.

        Yields:
            String chunks of the assistant response.
        """
        full_content = ""
        async for chunk in self._main_agent.chat_stream(
            message=message,
            session_id=session_id,
            tools=tools,
        ):
            full_content += chunk
            yield chunk

        # Journal write after stream completes (no intermediate trace in stream mode)
        self._write_journal(session_id, user_message=message, assistant_content=full_content)

    # ------------------------------------------------------------------
    # Approval / input gateway (unified across all managed agents)
    # ------------------------------------------------------------------

    def resolve_approval(
        self,
        request_id: str,
        decision: str,
        session_id: str = "default",
    ) -> None:
        """Resolve a pending tool approval request.

        Forwards to the main agent and all child agents so the decision
        reaches whichever agent is waiting.
        """
        self._main_agent.resolve_approval(request_id, decision, session_id)
        for child in self._child_agents.values():
            child.resolve_approval(request_id, decision, session_id)

    def provide_input(
        self,
        request_id: str,
        input_text: str,
        session_id: str = "default",
    ) -> None:
        """Provide input for a pending user-input request across all agents."""
        self._main_agent.provide_input(request_id, input_text, session_id)
        for child in self._child_agents.values():
            child.provide_input(request_id, input_text, session_id)

    def abort_execution(self, session_id: str = "default") -> None:
        """Signal abort for *session_id* (placeholder – log only for now)."""
        logger.info("Abort requested for session: %s", session_id)

    def add_tool_to_whitelist(
        self,
        tool_name: str,
        pattern: str = ".*",
        session_id: str = "default",
    ) -> None:
        """Add *tool_name* to the main agent's approval whitelist."""
        self._main_agent.add_tool_to_whitelist(tool_name, pattern, session_id)

    def remove_tool_from_whitelist(
        self,
        tool_name: str,
        session_id: str = "default",
    ) -> None:
        """Remove *tool_name* from the main agent's approval whitelist."""
        self._main_agent.remove_tool_from_whitelist(tool_name, session_id)

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
    # MessageBus integration
    # ------------------------------------------------------------------

    async def process_inbound_message(
        self,
        content: str,
        session_id: str = "default",
        use_tools: bool = False,  # kept for backward compat; ignored
    ) -> str:
        """Process an inbound message from the MessageBus.

        Delegates to :meth:`chat` so all inbound messages go through the
        full memory-saving and tool-execution pipeline.
        """
        response = await self.chat(content, session_id=session_id)
        return response.content

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
