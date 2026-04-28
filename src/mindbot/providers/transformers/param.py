"""Transformers provider parameters (stub)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mindbot.providers.param import BaseProviderParam


@dataclass
class TransformersProviderParam(BaseProviderParam):
    """Parameters for the HuggingFace Transformers provider (stub)."""

    model: str = ""
    device: str = "auto"
    torch_dtype: str = "auto"
    context_window: int | None = None  # model max context length (e.g., 2048 for small models)
    extra: dict[str, Any] = field(default_factory=dict)
