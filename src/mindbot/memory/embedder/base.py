"""Embedder abstraction for text-to-vector encoding."""

from __future__ import annotations

from abc import ABC, abstractmethod


class Embedder(ABC):
    """Abstract text embedder interface."""

    @abstractmethod
    async def encode(self, text: str) -> list[float]:
        """Encode a single text string to vector."""

    @abstractmethod
    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """Encode multiple texts to vectors."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Output vector dimension."""

    def encode_sync(self, text: str) -> list[float]:
        """Synchronous encode fallback (wraps async)."""
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, self.encode(text)).result()
        except RuntimeError:
            return asyncio.run(self.encode(text))

    def encode_batch_sync(self, texts: list[str]) -> list[list[float]]:
        """Synchronous batch encode fallback."""
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, self.encode_batch(texts)).result()
        except RuntimeError:
            return asyncio.run(self.encode_batch(texts))
