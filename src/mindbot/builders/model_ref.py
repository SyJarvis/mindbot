"""Unified model-reference parser – single source of truth.

Parses strings of the form ``provider/model_name`` (e.g. ``ollama/qwen3``),
and extracts the provider type and model identifier.

This module is intentionally dependency-free so it can be imported early
without triggering provider registration or circular imports.
"""

from __future__ import annotations

_DEFAULT_PROVIDER = "openai"


def parse_model_ref(model_ref: str) -> tuple[str, str]:
    """Return ``(provider_type, model_name)`` from a model reference string.

    Examples::

        parse_model_ref("ollama/qwen3")         # → ("ollama", "qwen3")
        parse_model_ref("openai/gpt-4o")        # → ("openai", "gpt-4o")
        parse_model_ref("gpt-4o")               # → ("openai", "gpt-4o")
        parse_model_ref("ollama/qwen3-vl:8b")   # → ("ollama", "qwen3-vl:8b")

    Args:
        model_ref: Model reference string, optionally prefixed with
            ``provider_type/``.

    Returns:
        A two-tuple ``(provider_type, model_name)``.
    """
    if not model_ref:
        raise ValueError("model_ref must not be empty")
    if "/" in model_ref:
        provider_type, model_name = model_ref.split("/", 1)
        if not provider_type:
            raise ValueError(f"Invalid model_ref (empty provider): {model_ref!r}")
        if not model_name:
            raise ValueError(f"Invalid model_ref (empty model name): {model_ref!r}")
        return provider_type, model_name
    # No slash – assume default provider
    return _DEFAULT_PROVIDER, model_ref
