"""EndpointManager – manages load balancing and failover across multiple endpoints.

The EndpointManager handles:
- Round-robin, random, and priority-based endpoint selection
- Tracking endpoint health (failure counts)
- Automatic fallback to healthy endpoints
"""

from __future__ import annotations

import random
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.mindbot.config.schema import Config, EndpointConfig

from src.mindbot.routing.models import EndpointCandidate


@dataclass
class EndpointHealth:
    """Health tracking for an endpoint."""

    failures: int = 0
    last_failure_time: float = 0.0
    last_success_time: float = 0.0
    is_healthy: bool = True

    def record_success(self) -> None:
        """Record a successful request."""
        self.failures = 0
        self.last_success_time = time.time()
        self.is_healthy = True

    def record_failure(self) -> None:
        """Record a failed request."""
        self.failures += 1
        self.last_failure_time = time.time()
        # Mark unhealthy after 3 consecutive failures
        if self.failures >= 3:
            self.is_healthy = False

    def should_try(self) -> bool:
        """Check if endpoint should be tried."""
        if self.is_healthy:
            return True
        # Try unhealthy endpoints after 60 seconds cooldown
        return time.time() - self.last_failure_time > 60


class EndpointManager:
    """Manages endpoint selection and health tracking.

    Supports three strategies:
    - round-robin: Rotate through endpoints in order
    - random: Randomly select endpoint (weighted by weight)
    - priority: Always try first endpoint, fall back to others on failure
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._health: dict[str, EndpointHealth] = defaultdict(EndpointHealth)
        self._round_robin_indices: dict[str, int] = defaultdict(int)

    def get_endpoint(
        self,
        instance: str,
        endpoint_index: str | None = None,
        strategy: str | None = None,
    ) -> EndpointCandidate:
        """Get an endpoint for the given provider instance.

        Args:
            instance: Provider instance name (user-chosen key in config.providers)
            endpoint_index: Specific endpoint index (if None, use strategy)
            strategy: Selection strategy (if None, use provider config)

        Returns:
            Selected endpoint candidate
        """
        provider_cfg = self._config.providers.get(instance)
        if not provider_cfg:
            raise ValueError(f"Provider instance not found: {instance}")

        endpoints = provider_cfg.get_effective_endpoints()
        if not endpoints:
            raise ValueError(f"No endpoints configured for provider instance: {instance}")

        # If specific endpoint requested, return it
        if endpoint_index is not None:
            idx = int(endpoint_index)
            if 0 <= idx < len(endpoints):
                return EndpointCandidate(
                    instance=instance,
                    endpoint_index=endpoint_index,
                    weight=endpoints[idx].weight,
                )

        # Use strategy to select endpoint
        strategy = strategy or provider_cfg.strategy
        idx = self._select_endpoint_index(instance, endpoints, strategy)
        return EndpointCandidate(
            instance=instance,
            endpoint_index=str(idx),
            weight=endpoints[idx].weight,
        )

    def get_all_healthy_endpoints(
        self,
        instance: str,
        include_unhealthy: bool = False,
    ) -> list[EndpointCandidate]:
        """Get all healthy endpoints for a provider instance.

        Args:
            instance: Provider instance name
            include_unhealthy: If True, include unhealthy endpoints at the end

        Returns:
            List of endpoint candidates, sorted by health
        """
        provider_cfg = self._config.providers.get(instance)
        if not provider_cfg:
            return []

        endpoints = provider_cfg.get_effective_endpoints()
        healthy = []
        unhealthy = []

        for idx, endpoint in enumerate(endpoints):
            key = f"{instance}:{idx}"
            health = self._health[key]

            candidate = EndpointCandidate(
                instance=instance,
                endpoint_index=str(idx),
                weight=endpoint.weight,
            )

            if health.should_try():
                healthy.append(candidate)
            else:
                unhealthy.append(candidate)

        result = healthy
        if include_unhealthy:
            result.extend(unhealthy)
        return result

    def record_success(self, instance: str, endpoint_index: str) -> None:
        """Record a successful request."""
        key = f"{instance}:{endpoint_index}"
        self._health[key].record_success()

    def record_failure(self, instance: str, endpoint_index: str) -> None:
        """Record a failed request."""
        key = f"{instance}:{endpoint_index}"
        self._health[key].record_failure()

    def get_health_status(self) -> dict[str, dict[str, Any]]:
        """Get health status for all endpoints."""
        result = {}
        for key, health in self._health.items():
            instance, endpoint_idx = key.split(":")
            result[key] = {
                "instance": instance,
                "endpoint_index": endpoint_idx,
                "is_healthy": health.is_healthy,
                "failures": health.failures,
                "last_success_time": health.last_success_time,
                "last_failure_time": health.last_failure_time,
            }
        return result

    def reset_health(self) -> None:
        """Reset all health tracking (useful after config reload)."""
        self._health.clear()
        self._round_robin_indices.clear()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _select_endpoint_index(
        self,
        instance: str,
        endpoints: list[EndpointConfig],
        strategy: str,
    ) -> int:
        """Select endpoint index based on strategy."""
        if strategy == "round-robin":
            return self._select_round_robin(instance, len(endpoints))
        elif strategy == "random":
            return self._select_weighted_random(endpoints)
        elif strategy == "priority":
            return self._select_priority(endpoints)
        else:
            return self._select_round_robin(instance, len(endpoints))

    def _select_round_robin(self, instance: str, count: int) -> int:
        """Select next endpoint in round-robin fashion."""
        idx = self._round_robin_indices[instance]
        self._round_robin_indices[instance] = (idx + 1) % count
        return idx

    @staticmethod
    def _select_weighted_random(endpoints: list[EndpointConfig]) -> int:
        """Select endpoint based on weight."""
        weights = [e.weight for e in endpoints]
        total_weight = sum(weights)
        if total_weight == 0:
            return random.randint(0, len(endpoints) - 1)

        r = random.uniform(0, total_weight)
        cumulative = 0
        for idx, weight in enumerate(weights):
            cumulative += weight
            if r <= cumulative:
                return idx
        return len(endpoints) - 1

    @staticmethod
    def _select_priority(endpoints: list[EndpointConfig]) -> int:
        """Always return first endpoint (priority mode)."""
        return 0
