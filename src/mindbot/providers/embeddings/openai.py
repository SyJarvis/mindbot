"""OpenAI-compatible embedder driver.

Works against any OpenAI-compatible ``/v1/embeddings`` endpoint
(OpenAI, vLLM, Ollama's ``/v1`` proxy, llama.cpp, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mindbot.providers.embeddings.base import Embedder
from mindbot.providers.embeddings.param import BaseEmbedderParam


@dataclass
class OpenAIEmbedderParam(BaseEmbedderParam):
    """Parameters for the OpenAI-compatible embedder driver."""

    model: str = "text-embedding-3-small"
    api_key: str | None = None
    base_url: str | None = None
    timeout: float = 60.0
    extra: dict[str, Any] = field(default_factory=dict)


class OpenAIEmbedder(Embedder):
    """OpenAI / OpenAI-compatible embedder.

    The constructor takes a single :class:`OpenAIEmbedderParam` so the
    embedder factory can instantiate it uniformly.  Internally we build
    an ``openai.AsyncOpenAI`` client just like
    :class:`mindbot.providers.openai.provider.OpenAIProvider`.
    """

    def __init__(self, param: OpenAIEmbedderParam) -> None:
        self._param = param
        self._dimension = param.dimension or 1536

        import openai

        kwargs: dict[str, Any] = {"timeout": param.timeout}
        if param.api_key:
            kwargs["api_key"] = param.api_key
        if param.base_url:
            kwargs["base_url"] = param.base_url
        self._client = openai.AsyncOpenAI(**kwargs)

    @property
    def dimension(self) -> int:
        return self._dimension

    def _dimensions_kwarg(self) -> int | None:
        """Only ``text-embedding-3-*`` accepts the ``dimensions`` parameter."""
        return self._dimension if self._param.model.startswith("text-embedding-3") else None

    async def encode(self, text: str) -> list[float]:
        response = await self._client.embeddings.create(
            model=self._param.model,
            input=text,
            dimensions=self._dimensions_kwarg(),
        )
        return response.data[0].embedding

    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        response = await self._client.embeddings.create(
            model=self._param.model,
            input=texts,
            dimensions=self._dimensions_kwarg(),
        )
        sorted_data = sorted(response.data, key=lambda x: x.index)
        return [item.embedding for item in sorted_data]
