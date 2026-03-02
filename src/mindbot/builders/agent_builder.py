"""Agent builder – unified entry point for creating Agent instances.

Usage::

    from mindbot.builders import create_agent, create_llm

    llm = create_llm(config)

    # Full agent from config (memory, approval, context all resolved from config)
    agent = create_agent(config, llm=llm, name="translator")

    # Minimal override – skip memory, use a custom system prompt
    agent = create_agent(
        config,
        llm=llm,
        name="polisher",
        system_prompt="你是文字润色专家",
        with_memory=False,
    )

The builder ensures:
* ``config.agent.approval`` is honoured (previously ``MindAgent`` ignored it
  and always created a fresh ``ToolApprovalConfig()``).
* ``config.memory.enable_fts`` is passed through to ``MemoryManager``.
* All parameter defaults flow from the config schema, not from scattered
  in-code literals.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mindbot.agent.agent import Agent
    from mindbot.capability.facade import CapabilityFacade
    from mindbot.config.schema import Config


def create_agent(
    config: "Config",
    *,
    llm: Any | None = None,
    name: str = "main",
    tools: list[Any] | None = None,
    system_prompt: str | None = None,
    with_memory: bool = True,
    capability_facade: "CapabilityFacade | None" = None,
) -> "Agent":
    """Construct a :class:`~mindbot.agent.agent.Agent` from *config*.

    All fields that were previously hard-coded inside ``MindAgent._build_main_agent``
    are now resolved from the config so the runtime behaviour matches what the
    user declared.

    Args:
        config: Root MindBot configuration.
        llm: Pre-built LLM adapter. If ``None``, :func:`create_llm` is called
            automatically.
        name: Agent name (used for logging and multi-agent identification).
        tools: Optional initial tool list.
        system_prompt: Override the agent's system prompt.  When ``None``,
            ``config.agent.system_prompt`` is used.
        with_memory: If ``False``, memory integration is skipped (useful for
            lightweight / test agents).
        capability_facade: Optional capability facade passed through to the
            orchestrator.

    Returns:
        A fully initialised :class:`~mindbot.agent.agent.Agent`.
    """
    from mindbot.agent.agent import Agent

    if llm is None:
        from mindbot.builders.llm_builder import create_llm
        llm = create_llm(config)

    memory = None
    if with_memory:
        from mindbot.memory.manager import MemoryManager
        memory = MemoryManager(
            storage_path=config.memory.storage_path,
            markdown_path=config.memory.markdown_path,
            short_term_retention_days=config.memory.short_term_retention_days,
            enable_fts=config.memory.enable_fts,
        )

    return Agent(
        name=name,
        llm=llm,
        tools=tools or [],
        system_prompt=system_prompt if system_prompt is not None else config.agent.system_prompt,
        approval_config=config.agent.approval,
        context_config=config.context,
        memory=memory,
        memory_top_k=config.agent.memory_top_k,
        max_iterations=config.agent.max_tool_iterations,
        max_sessions=config.agent.max_sessions,
        capability_facade=capability_facade,
    )
