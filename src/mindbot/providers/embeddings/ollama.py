"""Ollama embedder driver – talks to Ollama's native ``/api/embed`` endpoint.

Unlike :class:`mindbot.providers.embeddings.openai.OpenAIEmbedder`, Ollama
does not always expose an OpenAI-compatible ``/v1/embeddings`` path on the
default ``11434`` port, so we use Ollama's native batch endpoint directly.
Dimension is discovered lazily from the first call when not pre-declared.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mindbot.logging import logger
from mindbot.providers.embeddings.base import Embedder
from mindbot.providers.embeddings.param import BaseEmbedderParam


@dataclass
class OllamaEmbedderParam(BaseEmbedderParam):
    """Parameters for the Ollama embedder driver."""

    model: str = "qwen3-embedding:8b"
    base_url: str = "http://localhost:11434"
    api_key: str | None = None
    timeout: float = 60.0
    extra: dict[str, Any] = field(default_factory=dict)


class OllamaEmbedder(Embedder):
    """Embedder backed by a local (or remote) Ollama daemon.

    Uses the native ``/api/embed`` endpoint which accepts a list of strings
    in a single request.  The ``base_url`` should point at the Ollama root
    (without ``/v1`` suffix); we strip a trailing ``/v1`` if present so the
    same instance config can be reused with either embedder driver.
    """

    def __init__(self, param: OllamaEmbedderParam) -> None:
        self._param = param
        self._dimension: int | None = param.dimension

        base_url = (param.base_url or "http://localhost:11434").rstrip("/")
        if base_url.endswith("/v1"):
            base_url = base_url[: -len("/v1")]
        self._base_url = base_url

        self._headers: dict[str, str] = {}
        if param.api_key:
            self._headers["Authorization"] = f"Bearer {param.api_key}"

        self._async_client: Any = None
        self._client_loop_id: int | None = None

    @property
    def dimension(self) -> int:
        """Output vector dimension.

        Returns the configured value when set, otherwise a sentinel that
        callers should refresh via :meth:`encode` (which updates the cache
        once the model responds).  We default to ``0`` until a real call
        provides the answer; callers that depend on the dimension at init
        time (e.g. LanceDB table schema) should pass ``dimension`` in
        config to avoid the cold start.
        """
        if self._dimension is None:
            logger.warning(
                "OllamaEmbedder dimension unknown – set memory.vector.dimension "
                "to the model's output size to avoid LanceDB schema mismatches"
            )
            return 0
        return self._dimension

    def _get_client(self) -> Any:
        """Lazy httpx client mirroring :class:`OllamaProvider._get_client`."""
        import asyncio
        import httpx

        try:
            current_loop = asyncio.get_running_loop()
            current_loop_id = id(current_loop)
        except RuntimeError:
            current_loop_id = None

        if (
            self._async_client is None
            or self._async_client.is_closed
            or self._client_loop_id != current_loop_id
        ):
            self._async_client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._param.timeout,
                headers=self._headers or None,
            )
            self._client_loop_id = current_loop_id
        return self._async_client

    async def encode(self, text: str) -> list[float]:
        vectors = await self.encode_batch([text])
        return vectors[0] if vectors else []

    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        resp = await self._get_client().post(
            "/api/embed",
            json={"model": self._param.model, "input": texts},
        )
        resp.raise_for_status()
        data = resp.json()

        embeddings: list[list[float]] = data.get("embeddings") or []
        if not embeddings:
            # Legacy single-input endpoint as a fallback.
            single = data.get("embedding")
            if single is not None:
                embeddings = [single]

        if embeddings and self._dimension is None:
            self._dimension = len(embeddings[0])

        return embeddings
