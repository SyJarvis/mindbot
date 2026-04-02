"""Tests for ProviderFactory."""

from __future__ import annotations

import pytest

from mindbot.providers.factory import ProviderFactory
from mindbot.providers.param import BaseProviderParam
from mindbot.providers.openai.param import OpenAIProviderParam
from mindbot.providers.ollama.param import OllamaProviderParam


class TestProviderFactory:
    """Test ProviderFactory registration and creation."""

    def test_list_providers(self) -> None:
        """Should return list of registered provider names."""
        providers = ProviderFactory.list_providers()
        assert isinstance(providers, list)
        assert "openai" in providers
        assert "ollama" in providers
        assert "transformers" in providers

    def test_create_openai_with_dict(self) -> None:
        """Should create OpenAI provider from dict config."""
        provider = ProviderFactory.create("openai", {"model": "gpt-4o-mini", "api_key": "test"})
        assert provider.__class__.__name__ == "OpenAIProvider"

    def test_create_openai_with_param(self) -> None:
        """Should create OpenAI provider from param object."""
        param = OpenAIProviderParam(model="gpt-4o-mini", api_key="test")
        provider = ProviderFactory.create("openai", param)
        assert provider.__class__.__name__ == "OpenAIProvider"

    def test_create_ollama_with_dict(self) -> None:
        """Should create Ollama provider from dict config."""
        provider = ProviderFactory.create("ollama", {"model": "qwen3:1.7b"})
        assert provider.__class__.__name__ == "OllamaProvider"

    def test_create_ollama_with_param(self) -> None:
        """Should create Ollama provider from param object."""
        param = OllamaProviderParam(model="qwen3:1.7b")
        provider = ProviderFactory.create("ollama", param)
        assert provider.__class__.__name__ == "OllamaProvider"

    def test_create_unknown_provider_raises(self) -> None:
        """Should raise ValueError for unknown provider."""
        with pytest.raises(ValueError, match="Unknown provider"):
            ProviderFactory.create("unknown_provider", {})

    def test_create_with_wrong_param_type_raises(self) -> None:
        """Should raise TypeError when config type doesn't match."""
        with pytest.raises(TypeError):
            ProviderFactory.create("openai", "invalid_config")

    def test_error_message_shows_available_providers(self) -> None:
        """Error message should list available providers."""
        with pytest.raises(ValueError) as exc_info:
            ProviderFactory.create("bogus", {})

        error_msg = str(exc_info.value)
        assert "openai" in error_msg
        assert "ollama" in error_msg
