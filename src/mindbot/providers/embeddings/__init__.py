"""Embedding provider subsystem.

Register known embedder drivers on import, mirroring the explicit
registration policy used by :mod:`mindbot.providers` for chat providers.
"""

from mindbot.providers.embeddings.base import Embedder
from mindbot.providers.embeddings.factory import EmbedderFactory
from mindbot.providers.embeddings.ollama import OllamaEmbedder, OllamaEmbedderParam
from mindbot.providers.embeddings.openai import OpenAIEmbedder, OpenAIEmbedderParam
from mindbot.providers.embeddings.param import BaseEmbedderParam

EmbedderFactory.register("openai", OpenAIEmbedder, OpenAIEmbedderParam)
EmbedderFactory.register("ollama", OllamaEmbedder, OllamaEmbedderParam)

__all__ = [
    "Embedder",
    "EmbedderFactory",
    "BaseEmbedderParam",
    "OpenAIEmbedder",
    "OpenAIEmbedderParam",
    "OllamaEmbedder",
    "OllamaEmbedderParam",
]
