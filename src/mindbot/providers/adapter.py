"""Unified adapter that hides provider differences from callers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from mindbot.providers.factory import ProviderFactory

if TYPE_CHECKING:
    from mindbot.context.models import ChatResponse, Message, ProviderInfo
    from mindbot.capability.backends.tooling.models import Tool


class ProviderAdapter:
    """Public-facing adapter around any :class:`Provider`.

    Callers interact exclusively with this class; they never need to know
    which concrete provider is running underneath.
    """

    def __init__(
        self,
        provider_type: str,
        config: Any,
    ) -> None:
        # provider_type is the backend driver (e.g. "openai", "ollama").
        # config is a params dict like {"base_url": ..., "api_key": ..., "model": ...}
        # or a Pydantic ProviderInstanceConfig model.
        if hasattr(config, "get_effective_endpoints"):
            # ProviderInstanceConfig – extract first endpoint params
            endpoints = config.get_effective_endpoints()
            if endpoints:
                ep = endpoints[0]
                provider_config = {
                    "base_url": ep.base_url,
                    "api_key": ep.api_key,
                    "temperature": ep.temperature,
                    "max_tokens": ep.max_tokens,
                }
            else:
                provider_config = {}
            self._provider = ProviderFactory.create(provider_type, provider_config)
        elif isinstance(config, dict):
            self._provider = ProviderFactory.create(provider_type, config)
        else:
            self._provider = ProviderFactory.create(provider_type, config)

    # -- Chat -----------------------------------------------------------

    async def chat(
        self,
        messages: list[Message],
        model: str | None = None,
        tools: list[Tool] | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        return await self._provider.chat(messages, model=model, tools=tools, **kwargs)

    async def chat_stream(
        self,
        messages: list[Message],
        model: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        async for chunk in self._provider.chat_stream(messages, model=model, **kwargs):
            yield chunk

    # -- Embeddings -----------------------------------------------------

    async def embed(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        return await self._provider.embed(texts, **kwargs)

    # -- Tool binding ---------------------------------------------------

    def bind_tools(self, tools: list[Tool]) -> ProviderAdapter:
        """Return a **new** adapter with tools bound."""
        adapter = ProviderAdapter.__new__(ProviderAdapter)
        adapter._provider = self._provider.bind_tools(tools)
        return adapter

    # -- Introspection --------------------------------------------------

    def get_info(self) -> ProviderInfo:
        return self._provider.get_info()

    def get_model_list(self) -> list[str]:
        return self._provider.get_model_list()

    def supports_vision(self, model: str) -> bool:
        return self._provider.supports_vision(model)
