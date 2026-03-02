"""Data models for the routing system."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mindbot.config.schema import ModelConfig


@dataclass
class ModelCandidate:
    """A single (provider, endpoint, model) candidate for routing.

    Attributes:
        provider: Provider name (e.g., "openai", "ollama")
        endpoint_index: Index of the endpoint within the provider
        model_id: Model identifier
        level: Model capability level (low/medium/high)
        vision: Whether the model supports vision
        model_config: Full model config if available
    """

    provider: str
    endpoint_index: str
    model_id: str
    level: str
    vision: bool = False
    model_config: ModelConfig | None = None

    @property
    def key(self) -> str:
        """Unique key for this candidate."""
        return f"{self.provider}:{self.endpoint_index}:{self.model_id}"


@dataclass
class EndpointCandidate:
    """A single endpoint candidate for a provider.

    Attributes:
        provider: Provider name
        endpoint_index: Index of the endpoint
        weight: Load balancing weight
    """

    provider: str
    endpoint_index: str
    weight: int = 1

    @property
    def key(self) -> str:
        """Unique key for this endpoint."""
        return f"{self.provider}:{self.endpoint_index}"


@dataclass
class RoutingDecision:
    """The final routing decision including fallback chain and observability info.

    Attributes:
        provider: Selected provider name
        endpoint_index: Selected endpoint index
        model_id: Selected model ID
        level: Model capability level
        rule_hit: Which rule or strategy triggered this decision
        score: Complexity score if complexity routing was used
        fallbacks: List of (provider, endpoint_index, model_id) tuples for fallback
    """

    provider: str
    endpoint_index: str
    model_id: str
    level: str
    rule_hit: str | None = None
    score: float = 0.0
    fallbacks: list[tuple[str, str, str]] = field(default_factory=list)

    def __str__(self) -> str:
        chain = " → ".join(f"{p}/{e}/{m}" for p, e, m in self.fallbacks)
        fallback_info = f", fallbacks=[{chain}]" if self.fallbacks else ""
        return (
            f"RoutingDecision({self.provider}/{self.endpoint_index}/{self.model_id}, "
            f"level={self.level}, rule={self.rule_hit!r}"
            f"{fallback_info})"
        )

    @property
    def primary_key(self) -> str:
        """Primary selection key."""
        return f"{self.provider}:{self.endpoint_index}:{self.model_id}"
