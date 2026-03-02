"""llama_capp provider (stub – not yet implemented)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Self

from mindbot.providers.base import Provider
from mindbot.providers.llama_capp.param import LlamaCappProviderParam
from mindbot.context.models import ChatResponse, Message, ProviderInfo


class LlamaCappProvider(Provider):
    """Placeholder for the llama.cpp Python bindings provider."""

    def __init__(self, param: LlamaCappProviderParam) -> None:
        self._param = param

    async def chat(
        self,
        messages: list[Message],
        model: str | None = None,
        tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        raise NotImplementedError("llama_capp provider is not yet implemented")

    async def chat_stream(
        self,
        messages: list[Message],
        model: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        raise NotImplementedError("llama_capp provider is not yet implemented")
        yield ""  # make this a generator  # pragma: no cover

    async def embed(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        raise NotImplementedError("llama_capp provider is not yet implemented")

    def bind_tools(self, tools: list[Any]) -> Self:
        raise NotImplementedError("llama_capp provider is not yet implemented")

    def get_info(self) -> ProviderInfo:
        return ProviderInfo(
            provider="llama_capp",
            model=self._param.model or self._param.model_path,
            supports_vision=False,
            supports_tools=False,
        )
