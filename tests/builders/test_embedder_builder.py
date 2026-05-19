"""Tests for :func:`mindbot.builders.create_embedder`.

Covers the happy path (model_ref resolves through ``providers``),
empty-model-ref guard, missing-instance error, and parameter wiring
through to :class:`OpenAIEmbedder`.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from mindbot.builders import create_embedder
from mindbot.config.schema import Config
from mindbot.providers.embeddings.ollama import OllamaEmbedder
from mindbot.providers.embeddings.openai import OpenAIEmbedder


def _build_config(
    *,
    embedding_model: str,
    providers: dict | None = None,
    dimension: int = 1536,
) -> Config:
    """Helper that builds a Config focused on memory.vector + providers."""
    providers = (
        providers
        if providers is not None
        else {
            "openai": {
                "type": "openai",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-test",
            }
        }
    )
    return Config(
        agent={"model": "openai/gpt-4o-mini"},
        providers=providers,
        memory={
            "base_path": "~/.mindbot/memory",
            "content_path": "~/.mindbot/memory/content",
            "vector": {
                "enabled": True,
                "persist_path": "~/.mindbot/vectors",
                "dimension": dimension,
                "embedding_model": embedding_model,
            },
        },
    )


class TestCreateEmbedder:
    def test_creates_openai_embedder_from_model_ref(self) -> None:
        config = _build_config(embedding_model="openai/text-embedding-3-small")
        with patch("openai.AsyncOpenAI", lambda **_: object()):
            embedder = create_embedder(config)
        assert isinstance(embedder, OpenAIEmbedder)
        assert embedder.dimension == 1536

    def test_uses_dimension_from_config(self) -> None:
        config = _build_config(
            embedding_model="openai/text-embedding-3-small", dimension=512
        )
        with patch("openai.AsyncOpenAI", lambda **_: object()):
            embedder = create_embedder(config)
        assert embedder.dimension == 512

    def test_empty_embedding_model_raises(self) -> None:
        config = _build_config(embedding_model="")
        with pytest.raises(ValueError, match="memory.vector.embedding_model is required"):
            create_embedder(config)

    def test_unknown_instance_raises(self) -> None:
        config = _build_config(
            embedding_model="ghost/text-embedding-3-small",
            providers={
                "openai": {
                    "type": "openai",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "sk-test",
                }
            },
        )
        with pytest.raises(ValueError) as exc_info:
            create_embedder(config)
        msg = str(exc_info.value)
        assert "ghost" in msg
        assert "openai" in msg

    def test_unknown_driver_type_propagates_factory_error(self) -> None:
        config = _build_config(
            embedding_model="weirdo/bge-small",
            providers={
                "weirdo": {
                    "type": "no-such-driver",
                    "base_url": "http://example.invalid",
                }
            },
        )
        with pytest.raises(ValueError, match="Unknown embedder"):
            create_embedder(config)

    def test_credentials_propagate_from_provider_instance(self) -> None:
        captured: dict = {}

        def _fake_async_openai(**kwargs):
            captured.update(kwargs)
            return object()

        config = _build_config(
            embedding_model="openai/text-embedding-3-small",
            providers={
                "openai": {
                    "type": "openai",
                    "base_url": "https://example.com/v1",
                    "api_key": "sk-from-config",
                }
            },
        )
        with patch("openai.AsyncOpenAI", _fake_async_openai):
            create_embedder(config)

        assert captured.get("api_key") == "sk-from-config"
        assert captured.get("base_url") == "https://example.com/v1"

    def test_ollama_instance_routes_to_ollama_embedder(self) -> None:
        config = _build_config(
            embedding_model="local-ollama/qwen3-embedding:8b",
            providers={
                "local-ollama": {
                    "type": "ollama",
                    "endpoints": [
                        {"base_url": "http://localhost:11434", "weight": 1}
                    ],
                }
            },
            dimension=4096,
        )
        embedder = create_embedder(config)
        assert isinstance(embedder, OllamaEmbedder)
        assert embedder.dimension == 4096

    def test_endpoints_take_precedence_over_top_level(self) -> None:
        captured: dict = {}

        def _fake_async_openai(**kwargs):
            captured.update(kwargs)
            return object()

        config = _build_config(
            embedding_model="openai/text-embedding-3-small",
            providers={
                "openai": {
                    "type": "openai",
                    "base_url": "https://top-level.example/v1",
                    "api_key": "top-key",
                    "endpoints": [
                        {
                            "base_url": "https://endpoint.example/v1",
                            "api_key": "endpoint-key",
                        }
                    ],
                }
            },
        )
        with patch("openai.AsyncOpenAI", _fake_async_openai):
            create_embedder(config)

        assert captured.get("api_key") == "endpoint-key"
        assert captured.get("base_url") == "https://endpoint.example/v1"
