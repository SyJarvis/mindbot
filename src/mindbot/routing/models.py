"""Data models for the routing system."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.mindbot.config.schema import ModelConfig


@dataclass
class ModelCandidate:
    """A single (instance, endpoint, model) candidate for routing.

    Attributes:
        instance: Provider instance name (e.g., "local-ollama", "moonshot")
        provider_type: Backend driver type (e.g., "openai", "ollama")
        endpoint_index: Index of the endpoint within the provider instance
        model_id: Model identifier
        level: Model capability level (low/medium/high)
        vision: Whether the model supports vision
        model_config: Full model config if available
    """

    instance: str
    provider_type: str
    endpoint_index: str
    model_id: str
    level: str
    vision: bool = False
    model_config: ModelConfig | None = None

    @property
    def key(self) -> str:
        """Unique key for this candidate."""
        return f"{self.instance}:{self.endpoint_index}:{self.model_id}"


@dataclass
class EndpointCandidate:
    """A single endpoint candidate for a provider instance.

    Attributes:
        instance: Provider instance name
        endpoint_index: Index of the endpoint
        weight: Load balancing weight
    """

    instance: str
    endpoint_index: str
    weight: int = 1

    @property
    def key(self) -> str:
        """Unique key for this endpoint."""
        return f"{self.instance}:{self.endpoint_index}"


@dataclass
class RoutingDecision:
    """The final routing decision including fallback chain and observability info.

    Attributes:
        instance: Selected provider instance name
        provider_type: Backend driver type
        endpoint_index: Selected endpoint index
        model_id: Selected model ID
        level: Model capability level
        rule_hit: Which rule or strategy triggered this decision
        score: Complexity score if complexity routing was used
        fallbacks: List of (instance, endpoint_index, model_id) tuples for fallback
    """

    instance: str
    provider_type: str
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
            f"RoutingDecision({self.instance}/{self.endpoint_index}/{self.model_id}, "
            f"type={self.provider_type}, level={self.level}, rule={self.rule_hit!r}"
            f"{fallback_info})"
        )

    @property
    def primary_key(self) -> str:
        """Primary selection key."""
        return f"{self.instance}:{self.endpoint_index}:{self.model_id}"
