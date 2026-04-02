"""Provider factory – manual registration, no file scanning."""

from __future__ import annotations

from typing import Any

from src.mindbot.providers.base import Provider
from src.mindbot.providers.param import BaseProviderParam


class ProviderFactory:
    """Create provider instances by registered name.

    Providers are registered at import time in ``providers/__init__.py``
    using explicit ``register()`` calls.
    """

    _providers: dict[str, tuple[type[Provider], type[BaseProviderParam]]] = {}

    @classmethod
    def register(
        cls,
        name: str,
        provider_class: type[Provider],
        param_class: type[BaseProviderParam],
    ) -> None:
        """Register a provider type under *name*."""
        cls._providers[name] = (provider_class, param_class)

    @classmethod
    def create(cls, name: str, config: dict[str, Any] | BaseProviderParam) -> Provider:
        """Instantiate a provider by its registered *name*."""
        if name not in cls._providers:
            available = ", ".join(sorted(cls._providers)) or "(none)"
            raise ValueError(f"Unknown provider '{name}'. Registered: {available}")

        provider_class, param_class = cls._providers[name]

        if isinstance(config, dict):
            param = param_class(**config)
        elif isinstance(config, param_class):
            param = config
        else:
            raise TypeError(
                f"Expected dict or {param_class.__name__}, got {type(config).__name__}"
            )

        return provider_class(param)

    @classmethod
    def list_providers(cls) -> list[str]:
        """Return names of all registered providers."""
        return sorted(cls._providers)
