"""Abstract text embedder interface.

Embedders are first-class provider capabilities, peers to chat providers
under :mod:`mindbot.providers`.  They share the same provider-instance
configuration (``base_url`` / ``api_key`` / ``type``) but expose a
narrower surface tailored to vector storage callers such as
:class:`mindbot.memory.manager.MemoryManager`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class Embedder(ABC):
    """Abstract text embedder.

    Concrete implementations live alongside their chat counterparts inside
    :mod:`mindbot.providers.embeddings` and are registered with
    :class:`~mindbot.providers.embeddings.factory.EmbedderFactory`.
    """

    @abstractmethod
    async def encode(self, text: str) -> list[float]:
        """Encode a single text string to a vector."""

    @abstractmethod
    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """Encode multiple texts to vectors."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Output vector dimension. Source of truth for downstream stores."""

    def encode_sync(self, text: str) -> list[float]:
        """Synchronous encode fallback (wraps :meth:`encode`).

        Useful for legacy call sites that have not yet migrated to async;
        new code should prefer :meth:`encode` directly.
        """
        import asyncio

        try:
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, self.encode(text)).result()
        except RuntimeError:
            return asyncio.run(self.encode(text))
