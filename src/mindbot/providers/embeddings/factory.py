"""Embedder factory – manual registration mirroring ProviderFactory."""

from __future__ import annotations

import dataclasses
from typing import Any

from mindbot.providers.embeddings.base import Embedder
from mindbot.providers.embeddings.param import BaseEmbedderParam


class EmbedderFactory:
    """Create embedder instances by registered driver name.

    Embedder drivers are registered explicitly at import time inside
    :mod:`mindbot.providers.embeddings.__init__`, mirroring the manual
    registration policy used by
    :class:`mindbot.providers.factory.ProviderFactory`.
    """

    _embedders: dict[str, tuple[type[Embedder], type[BaseEmbedderParam]]] = {}

    @classmethod
    def register(
        cls,
        name: str,
        embedder_class: type[Embedder],
        param_class: type[BaseEmbedderParam],
    ) -> None:
        """Register an embedder driver under *name* (e.g. ``"openai"``)."""
        cls._embedders[name] = (embedder_class, param_class)

    @classmethod
    def create(
        cls, name: str, config: dict[str, Any] | BaseEmbedderParam
    ) -> Embedder:
        """Instantiate an embedder by its registered driver *name*."""
        if name not in cls._embedders:
            available = ", ".join(sorted(cls._embedders)) or "(none)"
            raise ValueError(
                f"Unknown embedder '{name}'. Registered: {available}"
            )

        embedder_class, param_class = cls._embedders[name]

        if isinstance(config, dict):
            valid_fields = {f.name for f in dataclasses.fields(param_class)}
            filtered = {
                k: v for k, v in config.items() if k in valid_fields and v is not None
            }
            param = param_class(**filtered)
        elif isinstance(config, param_class):
            param = config
        else:
            raise TypeError(
                f"Expected dict or {param_class.__name__}, got {type(config).__name__}"
            )

        return embedder_class(param)

    @classmethod
    def list_embedders(cls) -> list[str]:
        """Return names of all registered embedder drivers."""
        return sorted(cls._embedders)
