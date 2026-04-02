"""Tests for OpenAIProvider."""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mindbot.context.models import (
    Message,
    TextPart,
    ImagePart,
    ToolCall,
    FinishReason,
    ChatResponse,
)
from mindbot.providers.openai.provider import OpenAIProvider
from mindbot.providers.openai.param import OpenAIProviderParam


class TestOpenAIProviderInit:
    """Test OpenAIProvider initialization."""

    def test_init_with_minimal_params(self) -> None:
        """Should initialize with minimal parameters."""
        param = OpenAIProviderParam(model="gpt-4o-mini")
        with patch("openai.AsyncOpenAI"):
            provider = OpenAIProvider(param)
            assert provider._param.model == "gpt-4o-mini"

    def test_init_with_api_key(self) -> None:
        """Should pass api_key to OpenAI client."""
        param = OpenAIProviderParam(model="gpt-4o-mini", api_key="sk-test")
        with patch("openai.AsyncOpenAI") as mock_client:
            OpenAIProvider(param)
            mock_client.assert_called_once_with(api_key="sk-test")

    def test_init_with_base_url(self) -> None:
        """Should pass base_url to OpenAI client."""
        param = OpenAIProviderParam(model="gpt-4o-mini", base_url="https://api.example.com")
        with patch("openai.AsyncOpenAI") as mock_client:
            OpenAIProvider(param)
            mock_client.assert_called_once_with(base_url="https://api.example.com")

    def test_init_missing_openai_package_raises(self) -> None:
        """Should raise ImportError if openai package is not installed."""
        param = OpenAIProviderParam(model="gpt-4o-mini")
        with patch.dict("sys.modules", {"openai": None}):
            with pytest.raises(ImportError, match="Install the 'openai' package"):
                OpenAIProvider(param)


class TestOpenAIProviderChat:
    """Test OpenAIProvider.chat method."""

    @pytest.mark.asyncio
    async def test_chat_simple_message(
        self, mock_openai_client: MagicMock, sample_text_message: Message
    ) -> None:
        """Should send simple text message and receive response."""
        param = OpenAIProviderParam(model="gpt-4o-mini")
        with patch("openai.AsyncOpenAI", return_value=mock_openai_client):
            provider = OpenAIProvider(param)
            response = await provider.chat([sample_text_message])

            assert isinstance(response, ChatResponse)
            assert response.content == "Test response"
            assert response.provider.provider == "openai"
            assert response.provider.model == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_chat_with_multimodal_message(
        self, mock_openai_client: MagicMock, sample_multimodal_message: Message
    ) -> None:
        """Should handle messages with text and image content."""
        param = OpenAIProviderParam(model="gpt-4o-mini")
        with patch("openai.AsyncOpenAI", return_value=mock_openai_client):
            provider = OpenAIProvider(param)
            response = await provider.chat([sample_multimodal_message])

            assert response.content == "Test response"
            # Verify the client was called
            mock_openai_client.chat.completions.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_chat_with_conversation(
        self, mock_openai_client: MagicMock, sample_conversation: list[Message]
    ) -> None:
        """Should handle multi-turn conversation."""
        param = OpenAIProviderParam(model="gpt-4o-mini")
        with patch("openai.AsyncOpenAI", return_value=mock_openai_client):
            provider = OpenAIProvider(param)
            response = await provider.chat(sample_conversation)

            assert response.content == "Test response"

    @pytest.mark.asyncio
    async def test_chat_with_model_override(
        self, mock_openai_client: MagicMock, sample_text_message: Message
    ) -> None:
        """Should allow overriding model at call time."""
        param = OpenAIProviderParam(model="gpt-4o-mini")
        with patch("openai.AsyncOpenAI", return_value=mock_openai_client):
            provider = OpenAIProvider(param)
            response = await provider.chat([sample_text_message], model="gpt-4o")

            assert response.provider.model == "gpt-4o"

    @pytest.mark.asyncio
    async def test_chat_includes_usage_info(
        self, mock_openai_client: MagicMock, sample_text_message: Message
    ) -> None:
        """Should include token usage in response."""
        param = OpenAIProviderParam(model="gpt-4o-mini")
        with patch("openai.AsyncOpenAI", return_value=mock_openai_client):
            provider = OpenAIProvider(param)
            response = await provider.chat([sample_text_message])

            assert response.usage is not None
            assert response.usage.prompt_tokens == 10
            assert response.usage.completion_tokens == 5
            assert response.usage.total_tokens == 15


class TestOpenAIProviderChatStream:
    """Test OpenAIProvider.chat_stream method."""

    @pytest.mark.asyncio
    async def test_chat_stream_yields_chunks(
        self, mock_openai_client: MagicMock, sample_text_message: Message
    ) -> None:
        """Should yield text chunks during streaming."""
        # Setup streaming mock
        async def mock_stream_iter():
            chunks = [MagicMock(choices=[MagicMock(delta=MagicMock(content=c))]) for c in ["Hello", ", world", "!"]]
            for chunk in chunks:
                yield chunk

        mock_stream = MagicMock()
        mock_stream.__aiter__ = lambda self: mock_stream_iter()
        mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_stream)

        param = OpenAIProviderParam(model="gpt-4o-mini")
        with patch("openai.AsyncOpenAI", return_value=mock_openai_client):
            provider = OpenAIProvider(param)
            chunks = []
            async for chunk in provider.chat_stream([sample_text_message]):
                chunks.append(chunk)

            assert chunks == ["Hello", ", world", "!"]

    @pytest.mark.asyncio
    async def test_chat_stream_fallback_when_tools_bound(
        self, mock_openai_client: MagicMock, sample_text_message: Message
    ) -> None:
        """Should fall back to non-streaming when tools are bound."""
        param = OpenAIProviderParam(model="gpt-4o-mini")
        with patch("openai.AsyncOpenAI", return_value=mock_openai_client):
            provider = OpenAIProvider(param)
            # Bind tools (even empty list triggers fallback)
            bound_provider = provider.bind_tools([])
            chunks = []
            async for chunk in bound_provider.chat_stream([sample_text_message]):
                chunks.append(chunk)

            # Should get single chunk from non-streaming response
            assert len(chunks) == 1


class TestOpenAIProviderEmbed:
    """Test OpenAIProvider.embed method."""

    @pytest.mark.asyncio
    async def test_embed_single_text(self, mock_openai_client: MagicMock) -> None:
        """Should generate embedding for a single text."""
        param = OpenAIProviderParam(model="text-embedding-3-small")
        with patch("openai.AsyncOpenAI", return_value=mock_openai_client):
            provider = OpenAIProvider(param)
            embeddings = await provider.embed(["test text"])

            assert len(embeddings) == 1
            assert embeddings[0] == [0.1, 0.2, 0.3]

    @pytest.mark.asyncio
    async def test_embed_multiple_texts(self, mock_openai_client: MagicMock) -> None:
        """Should generate embeddings for multiple texts."""
        # Mock multiple embeddings
        mock_embedding = MagicMock()
        mock_embedding.data = [
            MagicMock(embedding=[0.1, 0.2, 0.3]),
            MagicMock(embedding=[0.4, 0.5, 0.6]),
        ]
        mock_openai_client.embeddings.create = AsyncMock(return_value=mock_embedding)

        param = OpenAIProviderParam(model="text-embedding-3-small")
        with patch("openai.AsyncOpenAI", return_value=mock_openai_client):
            provider = OpenAIProvider(param)
            embeddings = await provider.embed(["text1", "text2"])

            assert len(embeddings) == 2


class TestOpenAIProviderBindTools:
    """Test OpenAIProvider.bind_tools method."""

    def test_bind_tools_returns_new_instance(self) -> None:
        """Should return a new provider instance with tools bound."""
        param = OpenAIProviderParam(model="gpt-4o-mini")
        with patch("openai.AsyncOpenAI"):
            provider = OpenAIProvider(param)
            mock_tool = MagicMock()
            mock_tool.to_openai_format.return_value = {"type": "function"}

            bound = provider.bind_tools([mock_tool])

            # Should be different instance
            assert bound is not provider
            # Original should not have tools
            assert provider._bound_tools is None
            # Bound should have tools
            assert bound._bound_tools == [mock_tool]


class TestOpenAIProviderInfo:
    """Test OpenAIProvider info methods."""

    def test_get_info(self) -> None:
        """Should return provider metadata."""
        param = OpenAIProviderParam(model="gpt-4o-mini")
        with patch("openai.AsyncOpenAI"):
            provider = OpenAIProvider(param)
            info = provider.get_info()

            assert info.provider == "openai"
            assert info.model == "gpt-4o-mini"
            assert info.supports_tools is True

    def test_supports_vision_with_gpt4o(self) -> None:
        """Should detect vision support for gpt-4o models."""
        param = OpenAIProviderParam(model="gpt-4o-mini")
        with patch("openai.AsyncOpenAI"):
            provider = OpenAIProvider(param)
            assert provider.supports_vision("gpt-4o-mini") is True
            assert provider.supports_vision("gpt-4o") is True

    def test_supports_vision_with_o1(self) -> None:
        """Should detect vision support for o1 models."""
        param = OpenAIProviderParam(model="o1-preview")
        with patch("openai.AsyncOpenAI"):
            provider = OpenAIProvider(param)
            assert provider.supports_vision("o1-preview") is True
            assert provider.supports_vision("o3-mini") is True

    def test_supports_vision_with_non_vision_model(self) -> None:
        """Should return False for models without vision support."""
        param = OpenAIProviderParam(model="gpt-3.5-turbo")
        with patch("openai.AsyncOpenAI"):
            provider = OpenAIProvider(param)
            assert provider.supports_vision("gpt-3.5-turbo") is False

    def test_get_model_list_returns_empty(self) -> None:
        """Default implementation returns empty list."""
        param = OpenAIProviderParam(model="gpt-4o-mini")
        with patch("openai.AsyncOpenAI"):
            provider = OpenAIProvider(param)
            assert provider.get_model_list() == []


class TestOpenAIProviderMessageConversion:
    """Test internal message format conversion."""

    def test_to_openai_messages_text_only(self) -> None:
        """Should convert simple text message correctly."""
        param = OpenAIProviderParam(model="gpt-4o-mini")
        with patch("openai.AsyncOpenAI"):
            provider = OpenAIProvider(param)
            messages = [Message(role="user", content="Hello")]
            result = provider._to_openai_messages(messages)

            assert len(result) == 1
            assert result[0]["role"] == "user"
            assert result[0]["content"] == "Hello"

    def test_to_openai_messages_multimodal(self) -> None:
        """Should convert multimodal message correctly."""
        param = OpenAIProviderParam(model="gpt-4o-mini")
        with patch("openai.AsyncOpenAI"):
            provider = OpenAIProvider(param)
            messages = [
                Message(
                    role="user",
                    content=[
                        TextPart(text="What is this?"),
                        ImagePart(data=b"img_bytes", mime_type="image/png"),
                    ],
                )
            ]
            result = provider._to_openai_messages(messages)

            assert len(result) == 1
            assert result[0]["role"] == "user"
            assert isinstance(result[0]["content"], list)
            assert result[0]["content"][0]["type"] == "text"
            assert result[0]["content"][1]["type"] == "image_url"

    def test_to_openai_messages_with_tool_calls(self) -> None:
        """Should convert message with tool calls correctly."""
        param = OpenAIProviderParam(model="gpt-4o-mini")
        with patch("openai.AsyncOpenAI"):
            provider = OpenAIProvider(param)
            tool_call = ToolCall(id="call_1", name="test", arguments={"x": 1})
            messages = [Message(role="assistant", content="", tool_calls=[tool_call])]
            result = provider._to_openai_messages(messages)

            assert len(result) == 1
            assert result[0]["role"] == "assistant"
            assert "tool_calls" in result[0]
            assert len(result[0]["tool_calls"]) == 1
            assert result[0]["tool_calls"][0]["id"] == "call_1"

    def test_parse_response_with_finish_reason(self) -> None:
        """Should parse finish reason correctly."""
        param = OpenAIProviderParam(model="gpt-4o-mini")
        with patch("openai.AsyncOpenAI"):
            provider = OpenAIProvider(param)

            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message = MagicMock()
            mock_response.choices[0].message.content = "Test"
            mock_response.choices[0].message.tool_calls = None
            mock_response.choices[0].finish_reason = "tool_calls"
            mock_response.usage = None

            response = provider._parse_response(mock_response)

            assert response.finish_reason == FinishReason.TOOL_CALLS
