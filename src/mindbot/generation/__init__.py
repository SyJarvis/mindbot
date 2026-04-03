"""MindBot generation subsystem.

Provides the LLM-driven capability generation pipeline.  Phase 2 implements
the Tool-first path; the protocols layer is designed for Skill/MCP reuse.

Primary imports::

    from mindbot.generation import ToolGenerator, MockStrategy, PromptStrategy
    from mindbot.generation.models import ToolDefinition, ImplementationType
    from mindbot.generation.registry import ToolDefinitionRegistry
    from mindbot.generation.executor import DynamicToolExecutor
    from mindbot.generation.protocols import GenerationRequest, GenerationResult
"""

from mindbot.generation.executor import DynamicToolExecutor
from mindbot.generation.models import ImplementationType, ToolDefinition
from mindbot.generation.protocols import (
    GenerationRequest,
    GenerationResult,
    GenerationStatus,
)
from mindbot.generation.registry import ToolDefinitionRegistry
from mindbot.generation.system_prompt_builder import build_system_prompt
from mindbot.generation.tool_generator import MockStrategy, PromptStrategy, ToolGenerator
from mindbot.generation.validator import ToolDefinitionValidator

__all__ = [
    # Core models
    "ToolDefinition",
    "ImplementationType",
    # Protocols
    "GenerationRequest",
    "GenerationResult",
    "GenerationStatus",
    # Generation
    "ToolGenerator",
    "PromptStrategy",
    "MockStrategy",
    "ToolDefinitionValidator",
    # Persistence
    "ToolDefinitionRegistry",
    # Execution
    "DynamicToolExecutor",
    # Prompt builder
    "build_system_prompt",
]
