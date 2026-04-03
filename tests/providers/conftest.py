"""Fixtures for provider tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Generator
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any

import pytest

from mindbot.context.models import Message, TextPart, ImagePart, ToolCall
from mindbot.providers.openai.param import OpenAIProviderParam
from mindbot.providers.ollama.param import OllamaProviderParam


# ---------------------------------------------------------------------------
# Sample messages
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_text_message() -> Message:
    """A simple text message."""
    return Message(role="user", content="Hello, how are you?")


@pytest.fixture
def sample_multimodal_message() -> Message:
    """A message with text and image content."""
    return Message(
        role="user",
        content=[
            TextPart(text="What do you see in this image?"),
            ImagePart(data=b"fake_image_bytes", mime_type="image/png"),
        ],
    )


@pytest.fixture
def sample_conversation() -> list[Message]:
    """A simple conversation with multiple turns."""
    return [
        Message(role="system", content="You are a helpful assistant."),
        Message(role="user", content="What is 2+2?"),
        Message(role="assistant", content="2+2 equals 4."),
        Message(role="user", content="And what is 3+3?"),
    ]


@pytest.fixture
def sample_tool_calls() -> list[ToolCall]:
    """Sample tool calls for testing."""
    return [
        ToolCall(
            id="call_123",
            name="calculator",
            arguments={"operation": "add", "a": 2, "b": 2},
        )
    ]


# ---------------------------------------------------------------------------
# Mock OpenAI client
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_openai_client() -> Generator[MagicMock, None, None]:
    """Mock OpenAI AsyncOpenAI client."""
    with patch("openai.AsyncOpenAI") as mock_class:
        client = MagicMock()
        mock_class.return_value = client

        # Mock chat completions
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message = MagicMock()
        mock_completion.choices[0].message.content = "Test response"
        mock_completion.choices[0].message.tool_calls = None
        mock_completion.choices[0].finish_reason = "stop"
        mock_completion.usage = MagicMock()
        mock_completion.usage.prompt_tokens = 10
        mock_completion.usage.completion_tokens = 5
        mock_completion.usage.total_tokens = 15

        client.chat.completions.create = AsyncMock(return_value=mock_completion)

        # Mock embeddings
        mock_embedding = MagicMock()
        mock_embedding.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]
        client.embeddings.create = AsyncMock(return_value=mock_embedding)

        yield client


@pytest.fixture
def mock_openai_stream() -> Generator[AsyncMock, None, None]:
    """Mock OpenAI streaming response."""
    async def mock_stream_iter():
        chunks = ["Hello", ", world", "!"]
        for chunk in chunks:
            mock_chunk = MagicMock()
            mock_chunk.choices = [MagicMock()]
            mock_chunk.choices[0].delta = MagicMock()
            mock_chunk.choices[0].delta.content = chunk
            yield mock_chunk

    stream_mock = AsyncMock()
    stream_mock.__aiter__ = lambda self: mock_stream_iter()
    return stream_mock


# ---------------------------------------------------------------------------
# Mock httpx for Ollama
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_httpx_client() -> Generator[MagicMock, None, None]:
    """Mock httpx.AsyncClient for Ollama provider."""
    with patch("httpx.AsyncClient") as mock_class:
        client = MagicMock()

        # Mock POST /api/chat response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {
                "content": "Ollama response",
                "tool_calls": None,
            },
            "prompt_eval_count": 10,
            "eval_count": 5,
        }
        client.post = AsyncMock(return_value=mock_response)

        # Mock GET /api/tags for model list
        mock_tags_response = MagicMock()
        mock_tags_response.json.return_value = {
            "models": [
                {"model": "qwen3:1.7b", "name": "qwen3:1.7b"},
                {"model": "llama3:8b", "name": "llama3:8b"},
            ]
        }
        client.get = AsyncMock(return_value=mock_tags_response)

        mock_class.return_value = client
        yield client


@pytest.fixture
def mock_httpx_stream() -> Generator[AsyncMock, None, None]:
    """Mock httpx streaming response for Ollama."""
    async def mock_stream_lines():
        yield '{"message": {"content": "Stream"}}'
        yield '{"message": {"content": "ing"}}'
        yield '{"message": {"content": " text"}}'
        yield '{"done": true}'

    stream_mock = MagicMock()
    stream_mock.aiter_lines = mock_stream_lines
    return stream_mock


# ---------------------------------------------------------------------------
# Provider parameters
# ---------------------------------------------------------------------------

@pytest.fixture
def openai_param() -> OpenAIProviderParam:
    """Default OpenAI provider parameters."""
    return OpenAIProviderParam(
        model="gpt-4o-mini",
        api_key="test-key",
        temperature=0.7,
    )


@pytest.fixture
def ollama_param() -> OllamaProviderParam:
    """Default Ollama provider parameters."""
    return OllamaProviderParam(
        model="qwen3:1.7b",
        base_url="http://localhost:11434",
    )


# ---------------------------------------------------------------------------
# Async event loop
# ---------------------------------------------------------------------------

@pytest.fixture
def event_loop_policy() -> Any:
    """Ensure asyncio event loop is available."""
    import asyncio
    policy = asyncio.DefaultEventLoopPolicy()
    asyncio.set_event_loop_policy(policy)
    return policy
