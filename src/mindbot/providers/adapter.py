"""Unified adapter that hides provider differences from callers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from mindbot.providers.factory import ProviderFactory
from mindbot.providers.param import BaseProviderParam

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
        # Handle both dict configs and providers dict from Config
        if isinstance(config, dict) and provider_type in config:
            # Single provider config dict
            provider_config = config[provider_type]
            if hasattr(provider_config, "model_dump"):
                # Pydantic model - convert to dict
                provider_config = {
                    "base_url": provider_config.base_url,
                    "api_key": provider_config.api_key,
                    "temperature": provider_config.temperature,
                    "max_tokens": provider_config.max_tokens,
                }
            self._provider = ProviderFactory.create(provider_type, provider_config)
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
