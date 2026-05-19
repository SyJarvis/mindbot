"""Tests for EmbedderFactory.

Mirrors :mod:`tests.providers.test_factory` so the embedder factory has
the same baseline coverage as the chat provider factory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

# Ensure default drivers are registered.
import mindbot.providers.embeddings  # noqa: F401
from mindbot.providers.embeddings.base import Embedder
from mindbot.providers.embeddings.factory import EmbedderFactory
from mindbot.providers.embeddings.openai import OpenAIEmbedder, OpenAIEmbedderParam
from mindbot.providers.embeddings.param import BaseEmbedderParam


@dataclass
class FakeEmbedderParam(BaseEmbedderParam):
    """Test-only embedder param carrying an arbitrary tag string."""

    tag: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class FakeEmbedder(Embedder):
    """Test-only embedder that returns deterministic vectors."""

    def __init__(self, param: FakeEmbedderParam) -> None:
        self._param = param
        self._dimension = param.dimension or 4

    @property
    def dimension(self) -> int:
        return self._dimension

    async def encode(self, text: str) -> list[float]:
        return [float(len(text)) for _ in range(self._dimension)]

    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.encode(t) for t in texts]


@pytest.fixture(autouse=True)
def _register_fake_embedder():
    """Register and unregister a ``fake`` driver around each test."""
    EmbedderFactory.register("fake", FakeEmbedder, FakeEmbedderParam)
    try:
        yield
    finally:
        EmbedderFactory._embedders.pop("fake", None)


class TestEmbedderFactory:
    def test_list_embedders_includes_openai(self) -> None:
        embedders = EmbedderFactory.list_embedders()
        assert "openai" in embedders
        assert "fake" in embedders

    def test_create_openai_with_dict(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "openai.AsyncOpenAI", lambda **_: object()
        )
        embedder = EmbedderFactory.create(
            "openai",
            {"model": "text-embedding-3-small", "api_key": "test", "dimension": 1536},
        )
        assert isinstance(embedder, OpenAIEmbedder)
        assert embedder.dimension == 1536

    def test_create_openai_with_param(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "openai.AsyncOpenAI", lambda **_: object()
        )
        param = OpenAIEmbedderParam(
            model="text-embedding-3-small", api_key="test", dimension=512
        )
        embedder = EmbedderFactory.create("openai", param)
        assert isinstance(embedder, OpenAIEmbedder)
        assert embedder.dimension == 512

    def test_create_fake_driver_routes_to_registered_class(self) -> None:
        embedder = EmbedderFactory.create("fake", {"model": "dummy", "tag": "x"})
        assert isinstance(embedder, FakeEmbedder)
        assert embedder.dimension == 4

    def test_create_unknown_embedder_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown embedder"):
            EmbedderFactory.create("nonexistent", {})

    def test_unknown_driver_error_lists_available(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            EmbedderFactory.create("not-a-real-driver", {})
        msg = str(exc_info.value)
        assert "openai" in msg
        assert "fake" in msg

    def test_create_with_wrong_param_type_raises(self) -> None:
        with pytest.raises(TypeError):
            EmbedderFactory.create("openai", "invalid")

    def test_unknown_fields_are_filtered_when_using_dict(self, monkeypatch) -> None:
        monkeypatch.setattr("openai.AsyncOpenAI", lambda **_: object())
        embedder = EmbedderFactory.create(
            "openai",
            {
                "model": "text-embedding-3-small",
                "api_key": "test",
                "this_field_does_not_exist": True,
            },
        )
        assert isinstance(embedder, OpenAIEmbedder)


async def test_fake_embedder_round_trip() -> None:
    EmbedderFactory.register("fake-roundtrip", FakeEmbedder, FakeEmbedderParam)
    try:
        embedder = EmbedderFactory.create(
            "fake-roundtrip", {"model": "dummy", "dimension": 3}
        )
        vec = await embedder.encode("hi")
        assert vec == [2.0, 2.0, 2.0]
        batch = await embedder.encode_batch(["a", "bb"])
        assert batch == [[1.0, 1.0, 1.0], [2.0, 2.0, 2.0]]
    finally:
        EmbedderFactory._embedders.pop("fake-roundtrip", None)
