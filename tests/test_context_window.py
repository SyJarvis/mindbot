"""Tests for context_window auto-discovery from providers.

Verifies:
1. ProviderInfo carries context_window
2. Each provider reports its context_window
3. agent_builder auto-adjusts ContextConfig.max_tokens
4. ContextManager compression triggers at the right threshold
"""

import pytest
from unittest.mock import MagicMock, patch

from mindbot.context.models import ProviderInfo
from mindbot.config.schema import ContextConfig


# ---------------------------------------------------------------------------
# 1. ProviderInfo
# ---------------------------------------------------------------------------

class TestProviderInfoContextWindow:
    def test_default_is_none(self):
        info = ProviderInfo(provider="test", model="m")
        assert info.context_window is None

    def test_set_context_window(self):
        info = ProviderInfo(provider="hailo", model="qwen3:1.7b", context_window=2048)
        assert info.context_window == 2048


# ---------------------------------------------------------------------------
# 2. Hailo provider reports context_window
# ---------------------------------------------------------------------------

class TestHailoContextWindow:
    def test_model_context_window_map_exists(self):
        from mindbot.providers.hailo.provider import MODEL_CONTEXT_WINDOW
        assert "qwen3:1.7b" in MODEL_CONTEXT_WINDOW
        assert MODEL_CONTEXT_WINDOW["qwen3:1.7b"] == 2048

    def test_make_info_reports_context_window(self):
        from mindbot.providers.hailo.provider import HailoProvider, MODEL_CONTEXT_WINDOW
        from mindbot.providers.hailo.param import HailoProviderParam

        param = HailoProviderParam(model="qwen3:1.7b")
        with patch("mindbot.providers.hailo.provider._DeviceManager"):
            provider = HailoProvider(param)
            info = provider.get_info()
            assert info.context_window == MODEL_CONTEXT_WINDOW["qwen3:1.7b"]
            assert info.context_window == 2048

    def test_make_info_unknown_model_returns_none(self):
        from mindbot.providers.hailo.provider import HailoProvider
        from mindbot.providers.hailo.param import HailoProviderParam

        param = HailoProviderParam(model="unknown-model")
        with patch("mindbot.providers.hailo.provider._DeviceManager"):
            provider = HailoProvider(param)
            info = provider.get_info()
            assert info.context_window is None


# ---------------------------------------------------------------------------
# 3. Ollama / OpenAI providers pass through context_window from param
# ---------------------------------------------------------------------------

class TestOllamaContextWindow:
    def test_auto_detected_from_known_models(self):
        """When param.context_window is None, auto-detect from model table."""
        from mindbot.providers.ollama.provider import OllamaProvider
        from mindbot.providers.ollama.param import OllamaProviderParam

        param = OllamaProviderParam()  # default model qwen3:1.7b
        provider = OllamaProvider(param)
        info = provider.get_info()
        # qwen3:1.7b should auto-detect to 32768 from OLLAMA_MODEL_CONTEXT_WINDOW
        assert info.context_window == 32768

    def test_set_via_param(self):
        from mindbot.providers.ollama.provider import OllamaProvider
        from mindbot.providers.ollama.param import OllamaProviderParam

        param = OllamaProviderParam(context_window=8192)
        provider = OllamaProvider(param)
        info = provider.get_info()
        assert info.context_window == 8192

    def test_param_exceeds_limit_is_clamped(self):
        """If user sets context_window > model limit, clamp to limit."""
        from mindbot.providers.ollama.provider import OllamaProvider
        from mindbot.providers.ollama.param import OllamaProviderParam

        param = OllamaProviderParam(context_window=100000)  # exceeds 32768
        provider = OllamaProvider(param)
        info = provider.get_info()
        # Should be clamped to 32768 (auto-detected limit for qwen3:1.7b)
        assert info.context_window == 32768


class TestOpenAIContextWindow:
    def test_auto_detected_from_known_models(self):
        """When param.context_window is None, auto-detect from model table."""
        from mindbot.providers.openai.provider import OpenAIProvider
        from mindbot.providers.openai.param import OpenAIProviderParam

        with patch("openai.AsyncOpenAI"):
            param = OpenAIProviderParam()  # default model gpt-4o-mini
            provider = OpenAIProvider(param)
            info = provider.get_info()
            # gpt-4o-mini should auto-detect to 128000 from OPENAI_MODEL_CONTEXT_WINDOW
            assert info.context_window == 128000

    def test_set_via_param(self):
        from mindbot.providers.openai.provider import OpenAIProvider
        from mindbot.providers.openai.param import OpenAIProviderParam

        with patch("openai.AsyncOpenAI"):
            param = OpenAIProviderParam(context_window=4000)
            provider = OpenAIProvider(param)
            info = provider.get_info()
            assert info.context_window == 4000

    def test_param_exceeds_limit_is_clamped(self):
        """If user sets context_window > model limit, clamp to limit."""
        from mindbot.providers.openai.provider import OpenAIProvider
        from mindbot.providers.openai.param import OpenAIProviderParam

        with patch("openai.AsyncOpenAI"):
            param = OpenAIProviderParam(context_window=500000)  # exceeds 128000
            provider = OpenAIProvider(param)
            info = provider.get_info()
            # Should be clamped to 128000 (auto-detected limit for gpt-4o-mini)
            assert info.context_window == 128000


# ---------------------------------------------------------------------------
# 4. Provider base class get_context_window()
# ---------------------------------------------------------------------------

class TestProviderBaseContextWindow:
    def test_default_delegates_to_get_info(self):
        from mindbot.providers.base import Provider

        # Create a minimal concrete subclass
        class StubProvider(Provider):
            async def chat(self, messages, model=None, tools=None, **kw): pass
            async def chat_stream(self, messages, model=None, **kw): yield ""
            async def embed(self, texts, **kw): return []
            def bind_tools(self, tools): return self
            def get_info(self):
                return ProviderInfo(provider="stub", model="m", context_window=4096)

        p = StubProvider()
        assert p.get_context_window() == 4096

    def test_returns_none_when_not_set(self):
        from mindbot.providers.base import Provider

        class StubProvider(Provider):
            async def chat(self, messages, model=None, tools=None, **kw): pass
            async def chat_stream(self, messages, model=None, **kw): yield ""
            async def embed(self, texts, **kw): return []
            def bind_tools(self, tools): return self
            def get_info(self):
                return ProviderInfo(provider="stub", model="m")

        p = StubProvider()
        assert p.get_context_window() is None


# ---------------------------------------------------------------------------
# 5. agent_builder auto-adjusts context max_tokens
# ---------------------------------------------------------------------------

class TestAgentBuilderContextAdjust:
    def test_adjusts_when_provider_reports_smaller_window(self):
        """If provider reports context_window < config.context.max_tokens, adjust down."""
        from mindbot.builders.agent_builder import create_agent
        from mindbot.config.schema import Config, ContextConfig

        config = Config()
        config.context = ContextConfig(max_tokens=8000)

        mock_llm = MagicMock()
        mock_llm.get_info.return_value = ProviderInfo(
            provider="hailo", model="qwen3:1.7b", context_window=2048
        )

        with patch("mindbot.agent.agent.Agent") as MockAgent:
            create_agent(config, llm=mock_llm, include_builtin_tools=False, enable_dynamic_tools=False)

            call_kwargs = MockAgent.call_args[1]
            assert call_kwargs["context_config"].max_tokens == 2048

    def test_no_adjustment_when_provider_matches(self):
        """If provider context_window >= config, keep config value."""
        from mindbot.builders.agent_builder import create_agent
        from mindbot.config.schema import Config, ContextConfig

        config = Config()
        config.context = ContextConfig(max_tokens=8000)

        mock_llm = MagicMock()
        mock_llm.get_info.return_value = ProviderInfo(
            provider="ollama", model="qwen3:8b", context_window=32768
        )

        with patch("mindbot.agent.agent.Agent") as MockAgent:
            create_agent(config, llm=mock_llm, include_builtin_tools=False, enable_dynamic_tools=False)

            call_kwargs = MockAgent.call_args[1]
            assert call_kwargs["context_config"].max_tokens == 8000  # unchanged

    def test_no_adjustment_when_provider_reports_none(self):
        """If provider doesn't report context_window, keep config value."""
        from mindbot.builders.agent_builder import create_agent
        from mindbot.config.schema import Config, ContextConfig

        config = Config()
        config.context = ContextConfig(max_tokens=8000)

        mock_llm = MagicMock()
        mock_llm.get_info.return_value = ProviderInfo(
            provider="unknown", model="m", context_window=None
        )

        with patch("mindbot.agent.agent.Agent") as MockAgent:
            create_agent(config, llm=mock_llm, include_builtin_tools=False, enable_dynamic_tools=False)

            call_kwargs = MockAgent.call_args[1]
            assert call_kwargs["context_config"].max_tokens == 8000  # unchanged


# ---------------------------------------------------------------------------
# 6. ContextManager triggers compression at the right threshold
# ---------------------------------------------------------------------------

class TestContextManagerWithAdjustedBudget:
    def test_conversation_budget_with_hailo_window(self):
        """With context_window=2048, conversation budget should be ~716 tokens."""
        from mindbot.context.manager import _resolve_block_budgets

        config = ContextConfig(max_tokens=2048)
        budgets = _resolve_block_budgets(config)

        conv_budget = budgets["conversation"]
        assert conv_budget == int(2048 * 0.35)  # 716
        assert conv_budget < 2048  # always less than total

    def test_total_budgets_dont_exceed_window(self):
        """Sum of all block budgets should not exceed max_tokens."""
        from mindbot.context.manager import _resolve_block_budgets

        config = ContextConfig(max_tokens=2048)
        budgets = _resolve_block_budgets(config)
        total = sum(budgets.values())
        assert total <= 2048
