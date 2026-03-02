"""Ollama provider parameters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mindbot.providers.param import BaseProviderParam


@dataclass
class OllamaProviderParam(BaseProviderParam):
    """Parameters specific to the Ollama provider."""

    model: str = "qwen3:1.7b"
    base_url: str = "http://localhost:11434"
    api_key: str | None = None
    temperature: float = 0.7
    max_tokens: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    # Auto-pull configuration
    auto_pull: bool = False
    pull_method: str = "api"  # 'api', 'cli', or 'auto'
    pull_timeout: int = 600  # seconds to wait by default when ensuring a model
    preferred_models: list[str] = field(default_factory=list)
    pull_retries: int = 3
    pull_backoff: float = 2.0  # base seconds for exponential backoff
    pull_background: bool = True
