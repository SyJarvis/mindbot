"""ToolGenerator – produces ToolDefinition from a GenerationRequest.

This is the Tool-specific implementation of the universal generation
protocol (:mod:`mindbot.generation.protocols`).

Architecture
------------
The generator is deliberately strategy-driven so that tests and development
environments can inject a mock LLM call without touching production code.

The default :class:`PromptStrategy` renders a simple prompt, calls the
provider, and hands the raw response to the :class:`ToolDefinitionValidator`.
A ``MockStrategy`` is bundled for use in tests.

Usage::

    generator = ToolGenerator(llm_adapter)
    result = await generator.generate(
        GenerationRequest(description="Calculate the nth Fibonacci number")
    )
    if result.succeeded:
        defn: ToolDefinition = result.artifact
"""

from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable

from src.mindbot.generation.models import ToolDefinition
from src.mindbot.generation.protocols import (
    GenerationRequest,
    GenerationResult,
    GenerationStatus,
    GenerationValidationError,
)
from src.mindbot.generation.validator import ToolDefinitionValidator
from src.mindbot.utils import get_logger

logger = get_logger("generation.tool_generator")

_MAX_ATTEMPTS = 3


# ---------------------------------------------------------------------------
# Generation strategy protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class GenerationStrategy(Protocol):
    """Pluggable strategy for producing raw LLM output from a request."""

    async def call(self, request: GenerationRequest) -> str:
        """Invoke the strategy and return a raw string for the validator.

        Args:
            request: The generation request.

        Returns:
            Raw string output (typically JSON) ready for validation.
        """
        ...  # pragma: no cover


# ---------------------------------------------------------------------------
# Built-in strategies
# ---------------------------------------------------------------------------


class PromptStrategy:
    """Default strategy: build a prompt, call the provider, return raw text.

    Args:
        provider: Any object that exposes
            ``async chat(messages) -> ChatResponse``.  Typically a
            :class:`~mindbot.providers.adapter.ProviderAdapter`.
    """

    _SYSTEM_PROMPT = (
        "You are a tool definition generator. "
        "Given a description of a capability, output a JSON object with the following fields:\n"
        "- name: snake_case function name (alphanumeric + underscore, max 64 chars)\n"
        "- description: clear one-sentence description\n"
        "- parameters_schema: JSON Schema object with type=object and properties dict\n"
        "- implementation_type: always 'mock' unless otherwise instructed\n"
        "- implementation_ref: empty string unless implementation_type is 'callable'\n\n"
        "Output ONLY the JSON object with no extra text or markdown fences."
    )

    def __init__(self, provider: Any) -> None:
        self._provider = provider

    async def call(self, request: GenerationRequest) -> str:
        from src.mindbot.context.models import Message

        messages = [
            Message(role="system", content=self._SYSTEM_PROMPT),
            Message(
                role="user",
                content=(
                    f"Generate a tool definition for the following capability:\n\n"
                    f"{request.description}\n\n"
                    + (
                        f"Hints: {json.dumps(request.hints)}\n"
                        if request.hints
                        else ""
                    )
                ),
            ),
        ]
        response = await self._provider.chat(messages)
        return response.content


class MockStrategy:
    """Deterministic strategy for tests – returns a pre-built JSON string."""

    def __init__(self, override: dict[str, Any] | None = None) -> None:
        self._override = override or {}

    async def call(self, request: GenerationRequest) -> str:
        # Derive a snake_case name from the first few words of the description
        words = request.description.lower().split()[:4]
        name_parts = ["_".join(w for w in words if w.isalpha())]
        name = (name_parts[0] or "generated_tool").replace(" ", "_")[:64]

        definition: dict[str, Any] = {
            "name": name,
            "description": request.description,
            "parameters_schema": {
                "type": "object",
                "properties": {},
            },
            "implementation_type": "mock",
            "implementation_ref": "",
        }
        definition.update(self._override)
        return json.dumps(definition)


# ---------------------------------------------------------------------------
# ToolGenerator
# ---------------------------------------------------------------------------


class ToolGenerator:
    """Generates a :class:`~mindbot.generation.models.ToolDefinition` from a
    :class:`~mindbot.generation.protocols.GenerationRequest`.

    Args:
        strategy: A :class:`GenerationStrategy` that handles the actual LLM
            call.  Pass a :class:`PromptStrategy` for production use or a
            :class:`MockStrategy` for testing.
        max_attempts: Maximum number of validation retries before giving up.
    """

    def __init__(
        self,
        strategy: GenerationStrategy,
        *,
        max_attempts: int = _MAX_ATTEMPTS,
    ) -> None:
        self._strategy = strategy
        self._max_attempts = max_attempts
        self._validator = ToolDefinitionValidator()

    async def generate(self, request: GenerationRequest) -> GenerationResult[ToolDefinition]:
        """Run the generation flow.

        Args:
            request: What needs to be generated.

        Returns:
            A :class:`~mindbot.generation.protocols.GenerationResult` whose
            ``artifact`` is a valid :class:`~mindbot.generation.models.ToolDefinition`
            on success.
        """
        result: GenerationResult[ToolDefinition] = GenerationResult(
            request=request,
            status=GenerationStatus.GENERATING,
        )
        last_raw: str | None = None

        for attempt in range(1, self._max_attempts + 1):
            result.attempts = attempt
            logger.debug("Generation attempt %d/%d for '%s'", attempt, self._max_attempts, request.description[:60])

            try:
                raw = await self._strategy.call(request)
                last_raw = raw
                result.status = GenerationStatus.VALIDATING

                defn = self._validator.validate(raw, request)

                result.artifact = defn
                result.status = GenerationStatus.READY
                result.raw_output = raw
                logger.info("Generated tool '%s' in %d attempt(s)", defn.name, attempt)
                return result

            except GenerationValidationError as exc:
                logger.warning("Attempt %d validation failed: %s", attempt, exc)
                result.error = str(exc)
                result.raw_output = last_raw

        result.status = GenerationStatus.FAILED
        return result
