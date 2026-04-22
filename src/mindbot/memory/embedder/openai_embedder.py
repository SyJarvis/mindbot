"""OpenAI-compatible embedder implementation."""

from __future__ import annotations

from typing import Any

from mindbot.memory.embedder.base import Embedder
from mindbot.utils import get_logger

logger = get_logger("memory.openai_embedder")


class OpenAIEmbedder(Embedder):
    """OpenAI / OpenAI-compatible API embedder.

    Works with any OpenAI-compatible endpoint (OpenAI, Ollama, vLLM, etc.)
    """

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        base_url: str | None = None,
        api_key: str | None = None,
        dimension: int | None = None,  # For models that support flexible dimensions
        *,
        client: Any | None = None,  # Pre-built openai.AsyncOpenAI client
    ) -> None:
        self._model = model
        self._dimension = dimension or 1536
        self._client = client

        if client is None:
            import openai
            kwargs: dict[str, Any] = {}
            if base_url:
                kwargs["base_url"] = base_url
            if api_key:
                kwargs["api_key"] = api_key
            self._client = openai.AsyncOpenAI(**kwargs)

    @property
    def dimension(self) -> int:
        return self._dimension

    async def encode(self, text: str) -> list[float]:
        """Encode text using OpenAI embedding API."""
        response = await self._client.embeddings.create(
            model=self._model,
            input=text,
            dimensions=self._dimension if self._model.startswith("text-embedding-3") else None,
        )
        return response.data[0].embedding

    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """Encode multiple texts in a single API call."""
        if not texts:
            return []

        response = await self._client.embeddings.create(
            model=self._model,
            input=texts,
            dimensions=self._dimension if self._model.startswith("text-embedding-3") else None,
        )
        # Sort by index to ensure order
        sorted_data = sorted(response.data, key=lambda x: x.index)
        return [item.embedding for item in sorted_data]
