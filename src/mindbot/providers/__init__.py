"""Provider subsystem – register all known providers on import."""

from mindbot.providers.base import Provider
from mindbot.providers.factory import ProviderFactory
from mindbot.providers.ollama import OllamaProvider, OllamaProviderParam
from mindbot.providers.openai import OpenAIProvider, OpenAIProviderParam
from mindbot.providers.transformers import TransformersProvider, TransformersProviderParam

# Register providers (explicit, no file scanning – per DESIGN.md)
ProviderFactory.register("openai", OpenAIProvider, OpenAIProviderParam)
ProviderFactory.register("ollama", OllamaProvider, OllamaProviderParam)
ProviderFactory.register("transformers", TransformersProvider, TransformersProviderParam)

__all__ = [
    "Provider",
    "ProviderFactory",
    "OpenAIProvider",
    "OpenAIProviderParam",
    "OllamaProvider",
    "OllamaProviderParam",
    "TransformersProvider",
    "TransformersProviderParam",
]
