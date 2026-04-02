"""Multi-agent orchestration – sequential and parallel execution modes.

Uses the base :class:`~mindbot.agent.agent.Agent`, which runs through the
unified main path: ``InputBuilder.build()`` → ``TurnEngine.run()`` →
``PersistenceWriter.commit_turn()``.
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.mindbot.agent.agent import Agent
from src.mindbot.agent.models import AgentResponse, StopReason
from src.mindbot.utils import get_logger

logger = get_logger("agent.multi")


class AgentLaborMarket:
    """Registry of available Agents."""

    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    def register(self, agent: Agent) -> None:
        self._agents[agent.name] = agent

    def get(self, name: str) -> Agent | None:
        return self._agents.get(name)

    def list_agents(self) -> list[Agent]:
        return list(self._agents.values())


class MultiAgentOrchestrator:
    """Coordinate multiple Agents working on a task.

    Modes
    -----
    * **sequential** – A designated main agent (or the first registered agent)
      handles the full task.
    * **parallel** – All registered agents run concurrently on the same task;
      their responses are merged with a separator.

    Each agent in the pool is a fully-featured :class:`Agent` that uses the
    shared main path, so tool execution and conversation state remain
    consistent per-agent.
    """

    def __init__(self) -> None:
        self.labor_market = AgentLaborMarket()
        self.main_agent: Agent | None = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def register_agent(self, agent: Agent) -> None:
        """Register *agent* in the labor market."""
        self.labor_market.register(agent)

    def set_main_agent(self, agent: Agent) -> None:
        """Designate *agent* as the primary orchestrator for sequential mode."""
        self.main_agent = agent
        self.labor_market.register(agent)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute(
        self,
        task: str,
        session_id: str = "default",
        mode: str = "sequential",
        **kwargs: Any,
    ) -> AgentResponse:
        """Dispatch *task* using the chosen *mode*.

        Parameters
        ----------
        task:
            Natural-language description of the task.
        session_id:
            Session identifier passed to each agent.  In parallel mode each
            agent receives a namespaced variant (``<session_id>::<agent_name>``)
            to keep their contexts independent.
        mode:
            ``"sequential"`` or ``"parallel"``.
        """
        if mode == "sequential":
            return await self._execute_sequential(task, session_id=session_id)
        if mode == "parallel":
            return await self._execute_parallel(task, session_id=session_id)
        raise ValueError(f"Unknown mode: {mode!r}")

    # ------------------------------------------------------------------
    # Sequential
    # ------------------------------------------------------------------

    async def _execute_sequential(self, task: str, session_id: str) -> AgentResponse:
        """Main agent (or first registered) handles the task."""
        agent = self.main_agent
        if agent is None:
            agents = self.labor_market.list_agents()
            if not agents:
                raise RuntimeError("No agents registered")
            agent = agents[0]

        return await agent.chat(task, session_id=session_id)

    # ------------------------------------------------------------------
    # Parallel
    # ------------------------------------------------------------------

    async def _execute_parallel(self, task: str, session_id: str) -> AgentResponse:
        """Run all registered agents concurrently and merge their responses."""
        agents = self.labor_market.list_agents()
        if not agents:
            raise RuntimeError("No agents registered")

        # Each agent gets its own session namespace to avoid context collisions
        results: list[AgentResponse] = await asyncio.gather(
            *(
                agent.chat(task, session_id=f"{session_id}::{agent.name}")
                for agent in agents
            )
        )

        combined = "\n\n---\n\n".join(
            f"[{agents[i].name}]\n{r.content}" for i, r in enumerate(results)
        )

        return AgentResponse(
            content=combined,
            stop_reason=StopReason.COMPLETED,
        )
