"""Memory embedder module."""

from mindbot.memory.embedder.base import Embedder
from mindbot.memory.embedder.openai_embedder import OpenAIEmbedder

__all__ = [
    "Embedder",
    "OpenAIEmbedder",
]
