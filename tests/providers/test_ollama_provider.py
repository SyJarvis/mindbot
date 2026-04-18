"""Tests for OllamaProvider."""

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
from mindbot.providers.ollama.provider import OllamaProvider
from mindbot.providers.ollama.param import OllamaProviderParam


class TestOllamaProviderInit:
    """Test OllamaProvider initialization."""

    def test_init_with_minimal_params(self) -> None:
        """Should initialize with minimal parameters."""
        param = OllamaProviderParam(model="qwen3:1.7b")
        with patch("httpx.AsyncClient"):
            provider = OllamaProvider(param)
            assert provider._param.model == "qwen3:1.7b"
            assert provider._base_url == "http://localhost:11434"

    def test_init_with_base_url(self) -> None:
        """Should use custom base_url (lazy initialization)."""
        param = OllamaProviderParam(model="qwen3:1.7b", base_url="http://192.168.1.100:11434")
        with patch("httpx.AsyncClient") as mock_client:
            provider = OllamaProvider(param)
            # Client is not created during init (lazy initialization)
            mock_client.assert_not_called()
            # Trigger client creation via _get_client
            provider._get_client()
            mock_client.assert_called_once()
            call_kwargs = mock_client.call_args[1]
            assert call_kwargs["base_url"].rstrip("/") == "http://192.168.1.100:11434"

    def test_init_with_api_key(self) -> None:
        """Should set Authorization header when api_key is provided (lazy initialization)."""
        param = OllamaProviderParam(model="qwen3:1.7b", api_key="test-key")
        with patch("httpx.AsyncClient") as mock_client:
            provider = OllamaProvider(param)
            # Client is not created during init (lazy initialization)
            mock_client.assert_not_called()
            # Trigger client creation via _get_client
            provider._get_client()
            call_kwargs = mock_client.call_args[1]
            assert "Authorization" in call_kwargs["headers"]

    def test_init_missing_httpx_raises(self) -> None:
        """Should raise ImportError if httpx is not installed when _get_client is called."""
        param = OllamaProviderParam(model="qwen3:1.7b")
        provider = OllamaProvider(param)
        with patch.dict("sys.modules", {"httpx": None}):
            with pytest.raises(ModuleNotFoundError):
                provider._get_client()


class TestOllamaProviderChat:
    """Test OllamaProvider.chat method."""

    @pytest.mark.asyncio
    async def test_chat_simple_message(
        self, mock_httpx_client: MagicMock, sample_text_message: Message
    ) -> None:
        """Should send simple text message and receive response."""
        param = OllamaProviderParam(model="qwen3:1.7b")
        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            provider = OllamaProvider(param)
            response = await provider.chat([sample_text_message])

            assert isinstance(response, ChatResponse)
            assert response.content == "Ollama response"
            assert response.provider.provider == "ollama"
            assert response.provider.model == "qwen3:1.7b"

    @pytest.mark.asyncio
    async def test_chat_with_multimodal_message(
        self, mock_httpx_client: MagicMock, sample_multimodal_message: Message
    ) -> None:
        """Should handle messages with text and image content."""
        param = OllamaProviderParam(model="qwen3:1.7b")
        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            provider = OllamaProvider(param)
            response = await provider.chat([sample_multimodal_message])

            assert response.content == "Ollama response"
            mock_httpx_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_chat_with_conversation(
        self, mock_httpx_client: MagicMock, sample_conversation: list[Message]
    ) -> None:
        """Should handle multi-turn conversation."""
        param = OllamaProviderParam(model="qwen3:1.7b")
        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            provider = OllamaProvider(param)
            response = await provider.chat(sample_conversation)

            assert response.content == "Ollama response"

    @pytest.mark.asyncio
    async def test_chat_with_model_override(
        self, mock_httpx_client: MagicMock, sample_text_message: Message
    ) -> None:
        """Should allow overriding model at call time."""
        param = OllamaProviderParam(model="qwen3:1.7b")
        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            provider = OllamaProvider(param)
            response = await provider.chat([sample_text_message], model="llama3:8b")

            assert response.provider.model == "llama3:8b"

    @pytest.mark.asyncio
    async def test_chat_includes_usage_info(
        self, mock_httpx_client: MagicMock, sample_text_message: Message
    ) -> None:
        """Should include token usage in response when available."""
        param = OllamaProviderParam(model="qwen3:1.7b")
        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            provider = OllamaProvider(param)
            response = await provider.chat([sample_text_message])

            assert response.usage is not None
            assert response.usage.prompt_tokens == 10
            assert response.usage.completion_tokens == 5


class TestOllamaProviderChatStream:
    """Test OllamaProvider.chat_stream method."""

    @pytest.mark.asyncio
    async def test_chat_stream_yields_chunks(
        self, mock_httpx_client: MagicMock, sample_text_message: Message
    ) -> None:
        """Should yield text chunks during streaming."""
        # Setup streaming mock – httpx AsyncClient.stream() returns an async context manager
        async def mock_stream_lines():
            yield '{"message": {"content": "Streaming"}}'
            yield '{"message": {"content": "ing"}}'
            yield '{"message": {"content": " text"}}'
            yield '{"done": true}'

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()  # sync method
        mock_response.aiter_lines = mock_stream_lines  # async generator

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_httpx_client.stream = MagicMock(return_value=mock_cm)

        param = OllamaProviderParam(model="qwen3:1.7b")
        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            provider = OllamaProvider(param)
            chunks = []
            async for chunk in provider.chat_stream([sample_text_message]):
                chunks.append(chunk)

            assert chunks == ["Streaming", "ing", " text"]

    @pytest.mark.asyncio
    async def test_chat_stream_fallback_when_tools_bound(
        self, mock_httpx_client: MagicMock, sample_text_message: Message
    ) -> None:
        """Should fall back to non-streaming when tools are bound."""
        param = OllamaProviderParam(model="qwen3:1.7b")
        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            provider = OllamaProvider(param)
            bound_provider = provider.bind_tools([])
            chunks = []
            async for chunk in bound_provider.chat_stream([sample_text_message]):
                chunks.append(chunk)

            # Should get single chunk from non-streaming response
            assert len(chunks) == 1


class TestOllamaProviderEmbed:
    """Test OllamaProvider.embed method."""

    @pytest.mark.asyncio
    async def test_embed_single_text(self, mock_httpx_client: MagicMock) -> None:
        """Should generate embedding for a single text."""
        # Setup embedding mock
        mock_embed_response = MagicMock()
        mock_embed_response.json.return_value = {"embedding": [0.1, 0.2, 0.3]}
        mock_httpx_client.post = AsyncMock(return_value=mock_embed_response)

        param = OllamaProviderParam(model="qwen3:1.7b")
        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            provider = OllamaProvider(param)
            embeddings = await provider.embed(["test text"])

            assert len(embeddings) == 1
            assert embeddings[0] == [0.1, 0.2, 0.3]

    @pytest.mark.asyncio
    async def test_embed_multiple_texts(self, mock_httpx_client: MagicMock) -> None:
        """Should generate embeddings for multiple texts."""
        call_count = 0

        async def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"embedding": [0.1 * call_count, 0.2 * call_count, 0.3 * call_count]}
            return mock_resp

        mock_httpx_client.post = mock_post

        param = OllamaProviderParam(model="qwen3:1.7b")
        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            provider = OllamaProvider(param)
            embeddings = await provider.embed(["text1", "text2"])

            assert len(embeddings) == 2
            assert call_count == 2


class TestOllamaProviderBindTools:
    """Test OllamaProvider.bind_tools method."""

    def test_bind_tools_returns_new_instance(self) -> None:
        """Should return a new provider instance with tools bound."""
        param = OllamaProviderParam(model="qwen3:1.7b")
        with patch("httpx.AsyncClient"):
            provider = OllamaProvider(param)
            mock_tool = MagicMock()
            mock_tool.to_openai_format.return_value = {"type": "function"}

            bound = provider.bind_tools([mock_tool])

            # Should be different instance
            assert bound is not provider
            # Original should not have tools
            assert provider._bound_tools is None
            # Bound should have tools
            assert bound._bound_tools == [mock_tool]


class TestOllamaProviderInfo:
    """Test OllamaProvider info methods."""

    def test_get_info(self) -> None:
        """Should return provider metadata."""
        param = OllamaProviderParam(model="qwen3:1.7b")
        with patch("httpx.AsyncClient"):
            provider = OllamaProvider(param)
            info = provider.get_info()

            assert info.provider == "ollama"
            assert info.model == "qwen3:1.7b"
            assert info.supports_tools is True

    def test_supports_vision_with_vision_model(self) -> None:
        """Should detect vision support for vision-enabled models."""
        param = OllamaProviderParam(model="llama3.2-vision")
        with patch("httpx.AsyncClient"):
            provider = OllamaProvider(param)
            assert provider.supports_vision("llama3.2-vision") is True

    def test_supports_vision_with_non_vision_model(self) -> None:
        """Should return False for models without vision support."""
        param = OllamaProviderParam(model="qwen3:1.7b")
        with patch("httpx.AsyncClient"):
            provider = OllamaProvider(param)
            assert provider.supports_vision("qwen3:1.7b") is False


class TestOllamaProviderModelManagement:
    """Test OllamaProvider model management methods."""

    @pytest.mark.asyncio
    async def test_get_model_list(self, mock_httpx_client: MagicMock) -> None:
        """Should fetch list of available models."""
        # get_model_list() uses synchronous httpx.get, not AsyncClient
        mock_tags_resp = MagicMock()
        mock_tags_resp.json.return_value = {
            "models": [
                {"model": "qwen3:1.7b", "name": "qwen3:1.7b"},
                {"model": "llama3:8b", "name": "llama3:8b"},
            ]
        }
        mock_tags_resp.raise_for_status = MagicMock()

        param = OllamaProviderParam(model="qwen3:1.7b")
        with patch("httpx.AsyncClient", return_value=mock_httpx_client), \
             patch("httpx.get", return_value=mock_tags_resp):
            provider = OllamaProvider(param)
            models = provider.get_model_list()

            assert "qwen3:1.7b" in models
            assert "llama3:8b" in models

    @pytest.mark.asyncio
    async def test_list_local_models(self, mock_httpx_client: MagicMock) -> None:
        """Should async fetch list of local models."""
        param = OllamaProviderParam(model="qwen3:1.7b")
        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            provider = OllamaProvider(param)
            models = await provider.list_local_models()

            assert "qwen3:1.7b" in models

    @pytest.mark.asyncio
    async def test_is_model_available_true(self, mock_httpx_client: MagicMock) -> None:
        """Should return True when model is available."""
        param = OllamaProviderParam(model="qwen3:1.7b")
        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            provider = OllamaProvider(param)
            assert await provider.is_model_available("qwen3:1.7b") is True

    @pytest.mark.asyncio
    async def test_is_model_available_false(self, mock_httpx_client: MagicMock) -> None:
        """Should return False when model is not available."""
        param = OllamaProviderParam(model="qwen3:1.7b")
        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            provider = OllamaProvider(param)
            assert await provider.is_model_available("unknown:model") is False


class TestOllamaProviderMessageConversion:
    """Test internal message format conversion."""

    def test_to_ollama_messages_text_only(self) -> None:
        """Should convert simple text message correctly."""
        param = OllamaProviderParam(model="qwen3:1.7b")
        with patch("httpx.AsyncClient"):
            provider = OllamaProvider(param)
            messages = [Message(role="user", content="Hello")]
            result = provider._to_ollama_messages(messages)

            assert len(result) == 1
            assert result[0]["role"] == "user"
            assert result[0]["content"] == "Hello"

    def test_to_ollama_messages_multimodal(self) -> None:
        """Should convert multimodal message with images correctly."""
        param = OllamaProviderParam(model="llama3.2-vision")
        with patch("httpx.AsyncClient"):
            provider = OllamaProvider(param)
            messages = [
                Message(
                    role="user",
                    content=[
                        TextPart(text="What is this?"),
                        ImagePart(data=b"img_bytes", mime_type="image/png"),
                    ],
                )
            ]
            result = provider._to_ollama_messages(messages)

            assert len(result) == 1
            assert result[0]["role"] == "user"
            assert "images" in result[0]
            assert len(result[0]["images"]) == 1

    def test_to_ollama_messages_with_tool_calls(self) -> None:
        """Should convert message with tool calls correctly."""
        param = OllamaProviderParam(model="qwen3:1.7b")
        with patch("httpx.AsyncClient"):
            provider = OllamaProvider(param)
            tool_call = ToolCall(id="call_1", name="test", arguments={"x": 1})
            messages = [Message(role="assistant", content="", tool_calls=[tool_call])]
            result = provider._to_ollama_messages(messages)

            assert len(result) == 1
            assert result[0]["role"] == "assistant"
            assert "tool_calls" in result[0]
            assert len(result[0]["tool_calls"]) == 1

    def test_parse_response_with_tool_calls(self) -> None:
        """Should parse response with tool calls correctly."""
        param = OllamaProviderParam(model="qwen3:1.7b")
        with patch("httpx.AsyncClient"):
            provider = OllamaProvider(param)

            data = {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {
                                "name": "test",
                                "arguments": {"x": 1},
                            },
                        }
                    ],
                },
                "prompt_eval_count": 10,
                "eval_count": 5,
            }

            response = provider._parse_response(data)

            assert response.tool_calls is not None
            assert len(response.tool_calls) == 1
            assert response.tool_calls[0].name == "test"
            assert response.finish_reason == FinishReason.TOOL_CALLS
