"""Universal generation protocols.

All "generation" in MindBot (Tool, Skill, MCP, …) shares the same core
process:

    need description  →  LLM call  →  validated artifact  →  persist + register

The protocols in this module capture that shared structure.  Concrete
generators (e.g. :class:`~mindbot.generation.tool_generator.ToolGenerator`)
implement these protocols for their specific artifact type.  The *generation
flow* (prompt orchestration, retry, logging) can therefore be written once
and reused by all future artifact types.

Hierarchy
---------
::

    GenerationRequest          ← what the caller wants
    GenerationResult           ← what the generator produces
    ArtifactValidator          ← validates the raw LLM output
    ArtifactRenderer           ← converts to Capability for registration
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Generic, Protocol, TypeVar, runtime_checkable

# ---------------------------------------------------------------------------
# Type variable for the concrete artifact (ToolDefinition, SkillDefinition…)
# ---------------------------------------------------------------------------

ArtifactT = TypeVar("ArtifactT")


# ---------------------------------------------------------------------------
# Generation lifecycle
# ---------------------------------------------------------------------------


class GenerationStatus(str, Enum):
    """Lifecycle status of a generation attempt."""

    PENDING = "pending"
    GENERATING = "generating"
    VALIDATING = "validating"
    PERSISTING = "persisting"
    READY = "ready"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Request / Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GenerationRequest:
    """Caller-facing description of what needs to be generated.

    This is the only object the caller needs to construct; the concrete
    generator decides how to turn it into a prompt and what to do with
    the result.

    Attributes:
        description: Natural-language description of the desired capability.
        artifact_type: Target artifact type tag (``"tool"``, ``"skill"``,
            ``"mcp"``).  Used for routing and logging.
        context: Optional extra context (session state, prior attempts, user
            preferences) forwarded to the generator as-is.
        hints: Optional structured hints (e.g. parameter names, expected
            return type) that the generator may incorporate into the prompt.
    """

    description: str
    artifact_type: str = "tool"
    context: dict[str, Any] = field(default_factory=dict)
    hints: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.description.strip():
            raise ValueError("GenerationRequest.description must not be empty")


@dataclass
class GenerationResult(Generic[ArtifactT]):
    """Output of a generation attempt.

    Attributes:
        request: The originating request.
        status: Final lifecycle status.
        artifact: The validated artifact, or *None* if generation failed.
        error: Human-readable failure description, or *None* on success.
        attempts: Number of LLM calls made (useful for observability).
        raw_output: The last raw LLM output string (for debugging).
    """

    request: GenerationRequest
    status: GenerationStatus
    artifact: ArtifactT | None = None
    error: str | None = None
    attempts: int = 0
    raw_output: str | None = None

    @property
    def succeeded(self) -> bool:
        """True when the artifact is ready and usable."""
        return self.status == GenerationStatus.READY and self.artifact is not None


# ---------------------------------------------------------------------------
# Extension protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class ArtifactValidator(Protocol[ArtifactT]):
    """Validates a raw LLM output string into a typed artifact.

    Each artifact type provides its own validator.  The generation engine
    calls ``validate`` and retries when it raises.

    Example::

        class ToolDefinitionValidator:
            def validate(self, raw: str, request: GenerationRequest) -> ToolDefinition:
                ...
    """

    def validate(self, raw: str, request: GenerationRequest) -> ArtifactT:
        """Parse and validate *raw* LLM output.

        Args:
            raw: The raw string returned by the LLM.
            request: The originating generation request (may be used for
                context-aware validation).

        Returns:
            The validated, typed artifact.

        Raises:
            GenerationValidationError: When *raw* cannot be parsed or does not
                satisfy the artifact schema.
        """
        ...  # pragma: no cover


@runtime_checkable
class ArtifactRenderer(Protocol[ArtifactT]):
    """Converts a validated artifact into a
    :class:`~mindbot.capability.models.Capability`.

    The rendered capability is what gets registered in the
    :class:`~mindbot.capability.registry.CapabilityRegistry`.

    Example::

        class ToolDefinitionRenderer:
            def render(self, artifact: ToolDefinition) -> Capability:
                ...
    """

    def render(self, artifact: ArtifactT) -> Any:  # returns Capability
        """Convert *artifact* to a :class:`~mindbot.capability.models.Capability`.

        Args:
            artifact: The validated artifact produced by an
                :class:`ArtifactValidator`.

        Returns:
            A :class:`~mindbot.capability.models.Capability` suitable for
            registration.
        """
        ...  # pragma: no cover


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------


class GenerationError(Exception):
    """Base exception for all generation-layer errors."""


class GenerationValidationError(GenerationError):
    """Raised when the LLM output cannot be parsed into a valid artifact.

    Args:
        detail: Human-readable explanation of the validation failure.
        raw: The raw LLM output that failed validation, if available.
    """

    def __init__(self, detail: str, raw: str | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.raw = raw


class GenerationPersistenceError(GenerationError):
    """Raised when a generated artifact cannot be persisted to storage.

    Args:
        artifact_id: ID of the artifact that could not be persisted.
        cause: Underlying OS/IO exception.
    """

    def __init__(self, artifact_id: str, cause: BaseException | None = None) -> None:
        msg = f"Failed to persist artifact '{artifact_id}'"
        if cause is not None:
            msg = f"{msg}: {cause}"
        super().__init__(msg)
        self.artifact_id = artifact_id
        self.cause = cause
