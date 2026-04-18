"""RoutingProviderAdapter – dynamic per-call model/endpoint selection with fallback.

When ``config.routing.auto`` is ``True``, this adapter is used instead of a plain
``ProviderAdapter``. It presents the same interface so callers require no changes.

Features:
- Automatic model selection based on task type (vision/keywords/complexity)
- Load balancing across multiple endpoints
- Automatic fallback on failure
- Health tracking for endpoints
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mindbot.config.schema import Config
    from mindbot.context.models import ChatResponse, Message, ProviderInfo
    from mindbot.capability.backends.tooling.models import Tool

from mindbot.routing.router import ModelRouter
from mindbot.routing.endpoint import EndpointManager
from mindbot.routing.models import RoutingDecision
from mindbot.providers.adapter import ProviderAdapter


class RoutingProviderAdapter:
    """Wraps multiple :class:`ProviderAdapter` instances and selects the right
    one per request using :class:`ModelRouter` and :class:`EndpointManager`.

    Fallback behaviour:
    - If the primary (instance, endpoint, model) raises any exception, the adapter
      tries each fallback in order.
    - If all candidates fail, the last exception is re-raised with a structured
      message listing all attempted models.

    The class exposes the same interface as :class:`ProviderAdapter` so it
    can be used as a drop-in replacement.
    """

    def __init__(self, config: Config, bound_tools: list[Any] | None = None) -> None:
        self._config = config
        self._router = ModelRouter(config)
        self._endpoint_manager = EndpointManager(config)
        self._bound_tools: list[Any] = bound_tools or []
        # Cache of ProviderAdapter instances keyed by (instance, endpoint_index, model_id).
        self._adapters: dict[tuple[str, str, str], ProviderAdapter] = {}

    def invalidate_cache(self) -> None:
        """Clear adapter and router caches (used after config reload)."""
        self._adapters.clear()
        self._router.invalidate_cache()
        self._endpoint_manager.reset_health()

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[Message],
        model: str | None = None,
        tools: list[Tool] | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        decision = self._router.select_model(messages)
        from mindbot.utils import get_logger
        logger = get_logger("routing")
        logger.info("Routing decision: %s", decision)

        effective_tools = tools if tools is not None else (self._bound_tools or None)
        tried: list[str] = []
        last_exc: Exception | None = None

        # Try primary and fallbacks
        all_candidates = [(decision.instance, decision.endpoint_index, decision.model_id)]
        all_candidates.extend(decision.fallbacks)

        for instance, endpoint_idx, model_id in all_candidates:
            label = f"{instance}/{endpoint_idx}/{model_id}"
            tried.append(label)
            try:
                adapter = self._get_adapter(instance, endpoint_idx, model_id)
                result = await adapter.chat(
                    messages,
                    model=model or model_id,
                    tools=effective_tools,
                    **kwargs,
                )
                self._endpoint_manager.record_success(instance, endpoint_idx)
                return result
            except Exception as exc:
                logger.warning("Model %s failed: %s – trying fallback", label, exc)
                last_exc = exc
                self._endpoint_manager.record_failure(instance, endpoint_idx)

        raise RuntimeError(
            f"All routing candidates failed: {tried}. Last error: {last_exc}"
        ) from last_exc

    async def chat_stream(
        self,
        messages: list[Message],
        model: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        decision = self._router.select_model(messages)
        from mindbot.utils import get_logger
        logger = get_logger("routing")
        logger.info("Routing decision (stream): %s", decision)

        tried: list[str] = []
        last_exc: Exception | None = None

        all_candidates = [(decision.instance, decision.endpoint_index, decision.model_id)]
        all_candidates.extend(decision.fallbacks)

        for instance, endpoint_idx, model_id in all_candidates:
            label = f"{instance}/{endpoint_idx}/{model_id}"
            tried.append(label)
            try:
                adapter = self._get_adapter(instance, endpoint_idx, model_id)
                async for chunk in adapter.chat_stream(
                    messages, model=model or model_id, **kwargs
                ):
                    yield chunk
                self._endpoint_manager.record_success(instance, endpoint_idx)
                return
            except Exception as exc:
                logger.warning("Stream model %s failed: %s – trying fallback", label, exc)
                last_exc = exc
                self._endpoint_manager.record_failure(instance, endpoint_idx)

        raise RuntimeError(
            f"All routing candidates failed (stream): {tried}. Last error: {last_exc}"
        ) from last_exc

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------

    async def embed(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        """Embedding always uses the primary/default adapter (no routing)."""
        instance, model_id = self._parse_model_ref(self._config.agent.model)
        adapter = self._get_adapter(instance, "0", model_id)
        return await adapter.embed(texts, **kwargs)

    # ------------------------------------------------------------------
    # Tool binding (immutable pattern)
    # ------------------------------------------------------------------

    def bind_tools(self, tools: list[Tool]) -> RoutingProviderAdapter:
        """Return a **new** adapter with tools bound."""
        new = RoutingProviderAdapter.__new__(RoutingProviderAdapter)
        new._config = self._config
        new._router = self._router
        new._endpoint_manager = self._endpoint_manager
        new._bound_tools = list(tools)
        new._adapters = self._adapters  # share cache
        return new

    # ------------------------------------------------------------------
    # Introspection (delegate to the default model)
    # ------------------------------------------------------------------

    def get_info(self) -> ProviderInfo:
        """Get provider info for the default model."""
        instance, model_id = self._parse_model_ref(self._config.agent.model)
        return self._get_adapter(instance, "0", model_id).get_info()

    def get_model_list(self) -> list[str]:
        """Get all available models."""
        return self._router.get_model_list()

    def supports_vision(self, model: str) -> bool:
        """Check if a model supports vision."""
        parts = model.split("/")
        if len(parts) >= 2:
            instance = parts[0]
            model_id = parts[-1]
            endpoint_idx = parts[1] if len(parts) >= 3 else "0"
        else:
            return False

        try:
            return self._get_adapter(instance, endpoint_idx, model_id).supports_vision(model_id)
        except Exception:
            return False

    def get_health_status(self) -> dict[str, dict[str, Any]]:
        """Get health status for all endpoints."""
        return self._endpoint_manager.get_health_status()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_adapter(self, instance: str, endpoint_index: str, model_id: str) -> ProviderAdapter:
        """Return (and cache) a :class:`ProviderAdapter` for the given combination."""
        key = (instance, endpoint_index, model_id)
        if key not in self._adapters:
            import mindbot.providers  # noqa: F401

            provider_cfg = self._config.providers.get(instance)
            if not provider_cfg:
                raise ValueError(f"Provider instance not found: {instance}")

            endpoints = provider_cfg.get_effective_endpoints()
            idx = int(endpoint_index)
            if idx < 0 or idx >= len(endpoints):
                raise ValueError(f"Invalid endpoint index {idx} for provider instance {instance}")

            endpoint = endpoints[idx]
            params: dict[str, Any] = {
                "base_url": endpoint.base_url,
                "model": model_id,
            }
            if endpoint.api_key:
                params["api_key"] = endpoint.api_key
            if endpoint.temperature is not None:
                params["temperature"] = endpoint.temperature
            elif provider_cfg.temperature is not None:
                params["temperature"] = provider_cfg.temperature
            else:
                params["temperature"] = 0.7
            if endpoint.max_tokens is not None:
                params["max_tokens"] = endpoint.max_tokens

            # Extract vision flag from model config
            vision_enabled = self._get_model_vision_flag(endpoint, model_id)
            if vision_enabled:
                params["vision_enabled"] = True

            # Use provider_cfg.type as the driver type
            self._adapters[key] = ProviderAdapter(provider_cfg.type, params)
        return self._adapters[key]

    def _get_model_vision_flag(self, endpoint: Any, model_id: str) -> bool:
        """Extract vision flag from model config in endpoint."""
        for model in endpoint.models:
            if isinstance(model, str):
                if model == model_id:
                    return False
            elif hasattr(model, "id") and model.id == model_id:
                return getattr(model, "vision", False)
        return False

    @staticmethod
    def _parse_model_ref(model_ref: str) -> tuple[str, str]:
        """Parse 'instance/model' into (instance, model)."""
        if "/" in model_ref:
            parts = model_ref.split("/")
            if len(parts) >= 2:
                return parts[0], parts[-1]
        return "unknown", model_ref
