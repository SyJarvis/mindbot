"""Transformers provider (stub – not yet implemented)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Self

from src.mindbot.providers.base import Provider
from src.mindbot.providers.transformers.param import TransformersProviderParam
from src.mindbot.context.models import ChatResponse, Message, ProviderInfo


class TransformersProvider(Provider):
    """Placeholder for the HuggingFace Transformers provider."""

    def __init__(self, param: TransformersProviderParam) -> None:
        self._param = param

    async def chat(
        self,
        messages: list[Message],
        model: str | None = None,
        tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        raise NotImplementedError("transformers provider is not yet implemented")

    async def chat_stream(
        self,
        messages: list[Message],
        model: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        raise NotImplementedError("transformers provider is not yet implemented")
        yield ""  # pragma: no cover

    async def embed(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        raise NotImplementedError("transformers provider is not yet implemented")

    def bind_tools(self, tools: list[Any]) -> Self:
        raise NotImplementedError("transformers provider is not yet implemented")

    def get_info(self) -> ProviderInfo:
        return ProviderInfo(
            provider="transformers",
            model=self._param.model,
            supports_vision=False,
            supports_tools=False,
        )
