"""Transformers provider parameters (stub)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.mindbot.providers.param import BaseProviderParam


@dataclass
class TransformersProviderParam(BaseProviderParam):
    """Parameters for the HuggingFace Transformers provider (stub)."""

    model: str = ""
    device: str = "auto"
    torch_dtype: str = "auto"
    extra: dict[str, Any] = field(default_factory=dict)
