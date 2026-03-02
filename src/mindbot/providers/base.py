"""Abstract base class for all LLM/VLM providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, Self

if TYPE_CHECKING:
    from mindbot.context.models import ChatResponse, Message, ProviderInfo
    from mindbot.capability.backends.tooling.models import Tool


class Provider(ABC):
    """Every concrete provider must implement this interface.

    Design principles:
    - Async-first: ``chat``, ``chat_stream``, and ``embed`` are all ``async``.
    - ``model`` parameter on ``chat``/``chat_stream`` overrides the instance
      default, enabling the router to select a model without creating a new
      provider instance.
    - ``bind_tools`` returns a *new* provider instance (immutable pattern).
    - ``get_model_list`` and ``supports_vision`` have default no-op implementations;
      concrete providers should override them for accurate capability discovery.
    """

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------

    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        model: str | None = None,
        tools: list[Tool] | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        """Async chat completion.

        Parameters
        ----------
        messages:
            Conversation history (may include multimodal content).
        model:
            Override the instance-level default model if provided.
        tools:
            Tool definitions for this call; takes precedence over any tools
            previously bound via ``bind_tools``.
        """

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[Message],
        model: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Async streaming chat – yields text chunks as they arrive.

        When the provider has tools bound and the model triggers a function
        call, implementations should fall back to ``chat`` and yield the
        full text as a single chunk.
        """
        yield ""  # pragma: no cover

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------

    @abstractmethod
    async def embed(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        """Compute embedding vectors for *texts*."""

    # ------------------------------------------------------------------
    # Tool binding
    # ------------------------------------------------------------------

    @abstractmethod
    def bind_tools(self, tools: list[Tool]) -> Self:
        """Return a *new* provider instance with *tools* bound for function calling.

        The original instance is left unchanged (immutable pattern).
        """

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @abstractmethod
    def get_info(self) -> ProviderInfo:
        """Return metadata about this provider (provider, model, capabilities)."""

    def get_model_list(self) -> list[str]:
        """Return the list of model IDs available from this provider.

        Default returns an empty list; override for runtime discovery.
        """
        return []

    def supports_vision(self, model: str) -> bool:
        """Return ``True`` if *model* supports image/video input.

        Default returns ``False``; override with heuristics or API lookup.
        """
        return False
