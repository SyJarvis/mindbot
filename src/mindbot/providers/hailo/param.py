from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mindbot.providers.param import BaseProviderParam


@dataclass
class HailoProviderParam(BaseProviderParam):

    """Parameters specific to the Hailo LLM provider."""

    model: str = "qwen2.5-coder:1.5b"
    hef_base_path: str = "~/.local/share/hailo-ollama/models/blob"
    temperature: float = 0.7
    max_tokens: int = 0  # 0 = 不限制，模型在 <|im_end|> 自然停止
    vision_enabled: bool = False
    tools: list[dict[str, Any]] = field(default_factory=list)
    context_window: int | None = None  # override HEF context_window if set (but cannot exceed HEF limit)
    # Hailo-specific parameters can be added here
    extra: dict[str, Any] = field(default_factory=dict)