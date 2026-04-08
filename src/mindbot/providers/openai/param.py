"""OpenAI provider parameters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mindbot.providers.param import BaseProviderParam


@dataclass
class OpenAIProviderParam(BaseProviderParam):
    """Parameters specific to the OpenAI (and compatible) provider."""

    model: str = "gpt-4o-mini"
    api_key: str | None = None
    base_url: str | None = None
    timeout: float = 120.0
    temperature: float = 0.7
    max_tokens: int | None = None
    vision_enabled: bool = False
    extra: dict[str, Any] = field(default_factory=dict)
