"""Unified model-reference parser – single source of truth.

Parses strings of the form ``instance_name/model_name``
(e.g. ``local-ollama/qwen3``, ``moonshot/kimi-k2.5``).

This module is intentionally dependency-free so it can be imported early
without triggering provider registration or circular imports.
"""

from __future__ import annotations

_DEFAULT_INSTANCE = "local-ollama"


def parse_model_ref(model_ref: str) -> tuple[str, str]:
    """Return ``(instance_name, model_name)`` from a model reference string.

    The new format is ``instance_name/model_id``, where *instance_name*
    is the user-chosen key in ``config.providers``.

    Examples::

        parse_model_ref("local-ollama/qwen3")     # → ("local-ollama", "qwen3")
        parse_model_ref("moonshot/kimi-k2.5")     # → ("moonshot", "kimi-k2.5")
        parse_model_ref("qwen3")                  # → ("local-ollama", "qwen3")
        parse_model_ref("local-ollama/qwen3-vl:8b")  # → ("local-ollama", "qwen3-vl:8b")

    Args:
        model_ref: Model reference string, optionally prefixed with
            ``instance_name/``.

    Returns:
        A two-tuple ``(instance_name, model_name)``.
    """
    if not model_ref:
        raise ValueError("model_ref must not be empty")
    if "/" in model_ref:
        instance, model_name = model_ref.split("/", 1)
        if not instance:
            raise ValueError(f"Invalid model_ref (empty instance): {model_ref!r}")
        if not model_name:
            raise ValueError(f"Invalid model_ref (empty model name): {model_ref!r}")
        return instance, model_name
    # No slash – assume default instance
    return _DEFAULT_INSTANCE, model_ref
