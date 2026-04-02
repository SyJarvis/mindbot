"""LLM builder – unified entry point for creating provider adapters.

Usage::

    from mindbot.builders import create_llm

    llm = create_llm(config)  # ProviderAdapter or RoutingProviderAdapter

``create_llm`` respects ``config.routing.auto``:

* When routing is on  → ``RoutingProviderAdapter(config)``
* When routing is off → ``ProviderFactory.create(provider_type, params_dict)``

Centralises all provider-parsing and param-resolution logic that was
previously scattered across ``MindAgent._create_legacy_provider``,
``ProviderAdapter.__init__``, and ``RoutingProviderAdapter._get_adapter``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.mindbot.builders.model_ref import parse_model_ref

if TYPE_CHECKING:
    from src.mindbot.config.schema import Config


def create_llm(config: "Config") -> Any:
    """Create the appropriate LLM adapter from *config*.

    Returns either a :class:`~mindbot.providers.adapter.ProviderAdapter`
    (single-provider mode) or a
    :class:`~mindbot.routing.adapter.RoutingProviderAdapter` (routing mode).

    Args:
        config: Root MindBot configuration.

    Returns:
        An adapter that exposes ``chat`` / ``chat_stream`` / ``embed``.
    """
    if config.routing.auto:
        from src.mindbot.routing.adapter import RoutingProviderAdapter
        return RoutingProviderAdapter(config)

    instance_name, model_name = parse_model_ref(config.agent.model)
    provider_dict = _resolve_provider_params(config, instance_name, model_name)

    # Trigger provider registration before calling the factory
    import src.mindbot.providers  # noqa: F401
    from src.mindbot.providers.factory import ProviderFactory

    # Look up the driver type from the provider instance config
    provider_cfg = config.providers.get(instance_name)
    driver_type = provider_cfg.type if provider_cfg else instance_name

    return ProviderFactory.create(driver_type, provider_dict)


def _resolve_provider_params(
    config: "Config",
    instance_name: str,
    model_name: str,
) -> dict[str, Any]:
    """Build the provider param dict from *config* for *instance_name* / *model_name*.

    Resolution order:
    1. Endpoint entries (from ``providers[instance_name].endpoints``).
    2. Top-level provider config fields (``base_url``, ``api_key``, …).
    3. Minimal fallback (model name only) when provider not declared.

    Args:
        config: Root MindBot configuration.
        instance_name: Provider instance name (user-chosen key in config.providers).
        model_name: Model name passed through to the provider param.

    Returns:
        A dict suitable for ``ProviderFactory.create(driver_type, ...)``.
    """
    provider_config = config.providers.get(instance_name)
    if provider_config is None:
        return {"model": model_name}

    endpoints = provider_config.get_effective_endpoints()
    if endpoints:
        ep = endpoints[0]
        return {
            "base_url": ep.base_url,
            "api_key": ep.api_key,
            "temperature": ep.temperature,
            "max_tokens": ep.max_tokens,
            "model": model_name,
        }

    return {
        "base_url": provider_config.base_url or "",
        "api_key": provider_config.api_key,
        "temperature": provider_config.temperature,
        "max_tokens": provider_config.max_tokens,
        "model": model_name,
    }
