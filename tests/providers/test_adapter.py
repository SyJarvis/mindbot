"""Tests for ProviderAdapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mindbot.context.models import Message, ChatResponse
from mindbot.providers.adapter import ProviderAdapter
from mindbot.providers.openai.param import OpenAIProviderParam
from mindbot.providers.ollama.param import OllamaProviderParam


class TestProviderAdapterInit:
    """Test ProviderAdapter initialization."""

    def test_init_with_dict_config(self) -> None:
        """Should initialize with dict config."""
        with patch("openai.AsyncOpenAI"):
            adapter = ProviderAdapter("openai", {"model": "gpt-4o-mini", "api_key": "test"})
            assert adapter._provider is not None

    def test_init_with_pydantic_config(self) -> None:
        """Should initialize with Pydantic model config."""
        from mindbot.config.schema import ProviderInstanceConfig

        config = ProviderInstanceConfig(
            type="openai",
            endpoints=[{
                "base_url": "https://api.example.com",
                "api_key": "test-key",
                "temperature": 0.5,
                "max_tokens": 1000,
                "models": [{"id": "gpt-4o-mini"}],
            }],
        )

        with patch("openai.AsyncOpenAI"):
            adapter = ProviderAdapter("openai", config)
            assert adapter._provider is not None

    def test_init_with_param_object(self) -> None:
        """Should initialize with param object directly."""
        param = OpenAIProviderParam(model="gpt-4o-mini", api_key="test")
        with patch("openai.AsyncOpenAI"):
            adapter = ProviderAdapter("openai", param)
            assert adapter._provider is not None


class TestProviderAdapterChat:
    """Test ProviderAdapter.chat method."""

    @pytest.mark.asyncio
    async def test_chat_delegates_to_provider(self) -> None:
        """Should delegate chat call to underlying provider."""
        with patch("openai.AsyncOpenAI"):
            adapter = ProviderAdapter("openai", {"model": "gpt-4o-mini", "api_key": "test"})

            # Mock the provider's chat method
            mock_response = ChatResponse(content="Test response")
            adapter._provider.chat = AsyncMock(return_value=mock_response)

            response = await adapter.chat([Message(role="user", content="Hello")])

            assert response.content == "Test response"
            adapter._provider.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_chat_with_model_override(self) -> None:
        """Should pass model override to provider."""
        with patch("openai.AsyncOpenAI"):
            adapter = ProviderAdapter("openai", {"model": "gpt-4o-mini", "api_key": "test"})

            mock_response = ChatResponse(content="Test response")
            adapter._provider.chat = AsyncMock(return_value=mock_response)

            await adapter.chat([Message(role="user", content="Hello")], model="gpt-4o")

            adapter._provider.chat.assert_called_once()
            call_kwargs = adapter._provider.chat.call_args[1]
            assert call_kwargs["model"] == "gpt-4o"


class TestProviderAdapterChatStream:
    """Test ProviderAdapter.chat_stream method."""

    @pytest.mark.asyncio
    async def test_chat_stream_delegates_to_provider(self) -> None:
        """Should delegate streaming call to underlying provider."""
        with patch("openai.AsyncOpenAI"):
            adapter = ProviderAdapter("openai", {"model": "gpt-4o-mini", "api_key": "test"})

            # Mock streaming
            async def mock_stream(messages, model=None, **kwargs):
                for chunk in ["Hello", ", world", "!"]:
                    yield chunk

            adapter._provider.chat_stream = mock_stream

            chunks = []
            async for chunk in adapter.chat_stream([Message(role="user", content="Hello")]):
                chunks.append(chunk)

            assert chunks == ["Hello", ", world", "!"]


class TestProviderAdapterEmbed:
    """Test ProviderAdapter.embed method."""

    @pytest.mark.asyncio
    async def test_embed_delegates_to_provider(self) -> None:
        """Should delegate embed call to underlying provider."""
        with patch("openai.AsyncOpenAI"):
            adapter = ProviderAdapter("openai", {"model": "gpt-4o-mini", "api_key": "test"})

            adapter._provider.embed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])

            embeddings = await adapter.embed(["test text"])

            assert embeddings == [[0.1, 0.2, 0.3]]
            adapter._provider.embed.assert_called_once_with(["test text"])


class TestProviderAdapterBindTools:
    """Test ProviderAdapter.bind_tools method."""

    def test_bind_tools_returns_new_adapter(self) -> None:
        """Should return a new adapter with tools bound."""
        with patch("openai.AsyncOpenAI"):
            adapter = ProviderAdapter("openai", {"model": "gpt-4o-mini", "api_key": "test"})

            # Mock bind_tools on provider
            mock_bound_provider = MagicMock()
            adapter._provider.bind_tools = MagicMock(return_value=mock_bound_provider)

            mock_tool = MagicMock()

            bound_adapter = adapter.bind_tools([mock_tool])

            # Should be a new adapter instance
            assert bound_adapter is not adapter
            # Should have the bound provider
            assert bound_adapter._provider is mock_bound_provider
            # Original adapter should be unchanged
            adapter._provider.bind_tools.assert_called_once_with([mock_tool])


class TestProviderAdapterInfo:
    """Test ProviderAdapter info methods."""

    def test_get_info_delegates_to_provider(self) -> None:
        """Should delegate get_info to underlying provider."""
        with patch("openai.AsyncOpenAI"):
            adapter = ProviderAdapter("openai", {"model": "gpt-4o-mini", "api_key": "test"})

            mock_info = MagicMock()
            adapter._provider.get_info = MagicMock(return_value=mock_info)

            info = adapter.get_info()

            assert info is mock_info
            adapter._provider.get_info.assert_called_once()

    def test_get_model_list_delegates_to_provider(self) -> None:
        """Should delegate get_model_list to underlying provider."""
        with patch("openai.AsyncOpenAI"):
            adapter = ProviderAdapter("openai", {"model": "gpt-4o-mini", "api_key": "test"})

            adapter._provider.get_model_list = MagicMock(return_value=["model1", "model2"])

            models = adapter.get_model_list()

            assert models == ["model1", "model2"]

    def test_supports_vision_delegates_to_provider(self) -> None:
        """Should delegate supports_vision to underlying provider."""
        with patch("openai.AsyncOpenAI"):
            adapter = ProviderAdapter("openai", {"model": "gpt-4o-mini", "api_key": "test"})

            adapter._provider.supports_vision = MagicMock(return_value=True)

            assert adapter.supports_vision("gpt-4o-mini") is True
