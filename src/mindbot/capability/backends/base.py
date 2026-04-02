"""ExtensionBackend protocol – the single seam between the capability layer
and any concrete execution carrier (Tool, Skill, MCP, …).

Every carrier adapter must satisfy this protocol.  The capability executor
interacts with backends *exclusively* through this interface, so adding or
replacing a carrier never requires changes to the core layer.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from src.mindbot.capability.models import Capability


@runtime_checkable
class ExtensionBackend(Protocol):
    """A pluggable execution carrier.

    Implementors are responsible for:
    1. Advertising the capabilities they expose (``list_capabilities``).
    2. Executing a capability by ID when asked (``execute``).

    The capability executor calls ``list_capabilities`` at registration time
    to build its routing table and ``execute`` at call time.
    """

    def type_id(self) -> str:
        """Return the carrier type string: ``"tool"``, ``"skill"`` or ``"mcp"``."""
        ...  # pragma: no cover

    def list_capabilities(self) -> list[Capability]:
        """Return all capabilities currently exposed by this backend.

        The list may change between calls (e.g. after loading new dynamic
        tools), so callers should not cache the result indefinitely.
        """
        ...  # pragma: no cover

    async def execute(
        self,
        capability_id: str,
        arguments: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> str:
        """Execute the capability identified by *capability_id*.

        Args:
            capability_id: The globally unique capability ID to run.
            arguments: Call arguments (originate from the LLM's tool call or
                the orchestration layer).
            context: Optional session / step context that multi-step backends
                (e.g. Skill) may need.

        Returns:
            A string result suitable for feeding back to the LLM.

        Raises:
            CapabilityNotFoundError: If *capability_id* is not known to this
                backend.
            CapabilityExecutionError: If the backend encounters a runtime
                error during execution.
        """
        ...  # pragma: no cover
