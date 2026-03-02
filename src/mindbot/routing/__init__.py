"""Dynamic routing system for multi-provider, multi-model LLM management.

The routing system provides:
- ModelRouter: Select appropriate model based on task type (vision/keywords/complexity)
- EndpointManager: Manage load balancing and failover across multiple endpoints
- RoutingProviderAdapter: Unified interface that integrates both

Usage::

    from mindbot.routing import RoutingProviderAdapter

    adapter = RoutingProviderAdapter(config)
    response = await adapter.chat(messages)
    # Automatically routes to best model/endpoint
"""

from mindbot.routing.models import ModelCandidate, RoutingDecision
from mindbot.routing.router import ModelRouter
from mindbot.routing.endpoint import EndpointManager
from mindbot.routing.adapter import RoutingProviderAdapter

__all__ = [
    "ModelCandidate",
    "RoutingDecision",
    "ModelRouter",
    "EndpointManager",
    "RoutingProviderAdapter",
]
