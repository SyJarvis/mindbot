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
    from mindbot.capability.backends.tool_backend import ToolBackend
    from mindbot.capability.facade import CapabilityFacade
    from mindbot.config.schema import Config


def _merge_tools(*tool_groups: list[Any]) -> list[Any]:
    merged: dict[str, Any] = {}
    for group in tool_groups:
        for tool in group:
            tool_name = getattr(tool, "name", type(tool).__name__)
            merged[tool_name] = tool
    return list(merged.values())


def create_agent(
    config: "Config",
    *,
    llm: Any | None = None,
    name: str = "main",
    tools: list[Any] | None = None,
    include_builtin_tools: bool = True,
    enable_dynamic_tools: bool = True,
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
        include_builtin_tools: When ``True`` (default), attach the default
            built-in tool set before any caller-provided tools.
        enable_dynamic_tools: When ``True`` (default), load persisted dynamic
            tools and register the ``create_tool`` meta-tool.
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
        memory = MemoryManager.from_legacy_config(
            storage_path=config.memory.storage_path,
            markdown_path=config.memory.markdown_path,
            short_term_retention_days=config.memory.short_term_retention_days,
            enable_fts=config.memory.enable_fts,
        )

    skill_registry = None
    if config.skills.enabled:
        from mindbot.skills import SkillLoader

        skill_loader = SkillLoader(SkillLoader.default_roots(config.skills.skill_dirs))
        skill_registry = skill_loader.load_registry()

    builtin_tools: list[Any] = []
    if include_builtin_tools:
        from mindbot.tools import create_builtin_tools

        builtin_tools = create_builtin_tools(
            config.agent.workspace,
            restrict_to_workspace=config.agent.restrict_to_workspace,
            allowed_paths=[*config.agent.system_path_whitelist, *config.agent.trusted_paths],
            shell_execution_mode=config.agent.shell_execution.policy.value,
            shell_sandbox_provider=config.agent.shell_execution.sandbox_provider.value,
            shell_fail_if_unavailable=config.agent.shell_execution.fail_if_unavailable,
        )

    merged_tools = _merge_tools(builtin_tools, tools or [])

    tool_backend: "ToolBackend | None" = None
    dynamic_manager = None
    effective_facade = capability_facade

    if effective_facade is None:
        from mindbot.capability.backends.tool_backend import ToolBackend
        from mindbot.capability.backends.tooling.registry import ToolRegistry
        from mindbot.capability.facade import CapabilityFacade

        tool_backend = ToolBackend(
            static_registry=ToolRegistry.from_tools(merged_tools),
            auto_load=enable_dynamic_tools,
        )
        effective_facade = CapabilityFacade()
        effective_facade.add_backend(tool_backend)

    if enable_dynamic_tools and effective_facade is not None:
        from mindbot.capability.backends.tooling.meta_tool import create_tool_creation_tool
        from mindbot.generation.dynamic_manager import DynamicToolManager

        if tool_backend is None:
            from mindbot.capability.backends.tool_backend import ToolBackend
            from mindbot.capability.backends.tooling.registry import ToolRegistry

            tool_backend = ToolBackend(
                static_registry=ToolRegistry.from_tools(merged_tools),
                auto_load=True,
            )
            effective_facade.add_backend(tool_backend, replace=True)

        dynamic_manager = DynamicToolManager(
            llm=llm,
            capability_facade=effective_facade,
            tool_backend=tool_backend,
        )
        create_tool_meta = create_tool_creation_tool(dynamic_manager)
        tool_backend.register_static(create_tool_meta, replace=True)
        merged_tools = _merge_tools(merged_tools, [create_tool_meta])
        effective_facade.refresh_registry()

    return Agent(
        name=name,
        llm=llm,
        tools=merged_tools,
        system_prompt=system_prompt if system_prompt is not None else config.agent.system_prompt,
        context_config=config.context,
        memory=memory,
        memory_top_k=config.agent.memory_top_k,
        tool_persistence=config.agent.tool_persistence.value,
        max_iterations=config.agent.max_tool_iterations,
        max_sessions=config.agent.max_sessions,
        capability_facade=effective_facade,
        tool_backend=tool_backend,
        dynamic_manager=dynamic_manager,
        skill_registry=skill_registry,
        skills_config=config.skills,
    )
