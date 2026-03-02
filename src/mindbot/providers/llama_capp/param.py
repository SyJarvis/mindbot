"""llama_capp provider parameters (stub)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mindbot.providers.param import BaseProviderParam


@dataclass
class LlamaCappProviderParam(BaseProviderParam):
    """Parameters for the llama.cpp provider (stub)."""

    model: str = ""
    model_path: str = ""
    n_ctx: int = 4096
    n_gpu_layers: int = -1
    extra: dict[str, Any] = field(default_factory=dict)
