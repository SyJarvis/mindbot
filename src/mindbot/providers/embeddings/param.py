"""Base parameter definitions for embedding providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BaseEmbedderParam:
    """Common parameters shared by all embedders.

    Mirrors :class:`mindbot.providers.param.BaseProviderParam` so the
    embedder factory can reuse the same dict-or-dataclass plumbing.
    """

    model: str = ""
    dimension: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)
