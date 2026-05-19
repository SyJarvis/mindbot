"""Embedder builder – single entry point for creating an :class:`Embedder`.

Usage::

    from mindbot.builders import create_embedder

    embedder = create_embedder(config)

Resolution mirrors :func:`mindbot.builders.llm_builder.create_llm`:

1. Parse ``config.memory.vector.embedding_model`` as ``instance/model``
   using :func:`mindbot.builders.model_ref.parse_model_ref`.
2. Look up the matching ``ProviderInstanceConfig`` in
   ``config.providers`` to obtain ``type``, ``base_url`` and ``api_key``.
3. Build the embedder param dict and delegate to
   :meth:`mindbot.providers.embeddings.factory.EmbedderFactory.create`.

The builder rejects empty ``embedding_model`` values or unknown instance
references with a :class:`ValueError`.  There is no backward-compatible
fallback – the legacy memory-vector embedder fields were removed when
this builder was introduced.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mindbot.builders.model_ref import parse_model_ref

if TYPE_CHECKING:
    from mindbot.config.schema import Config
    from mindbot.providers.embeddings.base import Embedder


def create_embedder(config: "Config") -> "Embedder":
    """Create an :class:`Embedder` from the root MindBot *config*.

    Raises:
        ValueError: If ``memory.vector.embedding_model`` is empty, the
            instance is not declared under ``providers``, or the
            instance type maps to an unregistered embedder driver.
    """
    vector_cfg = config.memory.vector
    model_ref = vector_cfg.embedding_model

    if not model_ref:
        raise ValueError(
            "memory.vector.embedding_model is required, e.g. "
            "'openai/text-embedding-3-small'."
        )

    instance_name, model_name = parse_model_ref(model_ref)

    provider_cfg = config.providers.get(instance_name)
    if provider_cfg is None:
        available = ", ".join(sorted(config.providers)) or "(none)"
        raise ValueError(
            f"memory.vector.embedding_model references provider instance "
            f"'{instance_name}' which is not declared under "
            f"`providers`. Available: {available}"
        )

    driver_type = provider_cfg.type or instance_name
    param_dict = _resolve_embedder_params(provider_cfg, model_name, vector_cfg.dimension)

    import mindbot.providers.embeddings  # noqa: F401 - triggers driver registration
    from mindbot.providers.embeddings.factory import EmbedderFactory

    return EmbedderFactory.create(driver_type, param_dict)


def _resolve_embedder_params(
    provider_cfg: Any,
    model_name: str,
    dimension: int | None,
) -> dict[str, Any]:
    """Build the embedder param dict from a ``ProviderInstanceConfig``.

    Endpoints take precedence over the legacy top-level
    ``base_url`` / ``api_key`` fields, mirroring
    :func:`mindbot.builders.llm_builder._resolve_provider_params`.
    """
    endpoints = provider_cfg.get_effective_endpoints()
    if endpoints:
        ep = endpoints[0]
        return {
            "model": model_name,
            "dimension": dimension,
            "base_url": ep.base_url or None,
            "api_key": ep.api_key or None,
        }

    return {
        "model": model_name,
        "dimension": dimension,
        "base_url": provider_cfg.base_url or None,
        "api_key": provider_cfg.api_key or None,
    }
