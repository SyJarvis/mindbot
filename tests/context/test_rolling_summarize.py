from __future__ import annotations

from typing import Any
from collections.abc import AsyncIterator

import pytest

from mindbot.context.compression import (
    RollingSummarizeStrategy,
    _SUMMARY_MARKER,
    get_strategy,
)
from mindbot.context.models import ChatResponse, FinishReason, Message
from mindbot.utils import estimate_tokens


def _msg(role: str, text: str) -> Message:
    return Message(role=role, content=text)


class FakeLLM:
    def __init__(self, replies: list[str] | None = None) -> None:
        self._replies = list(replies or ["summary"])
        self._idx = 0
        self.chat_calls: list[list[Message]] = []

    async def chat(self, messages: list[Message], **kwargs: Any) -> ChatResponse:
        self.chat_calls.append(messages)
        reply = self._replies[min(self._idx, len(self._replies) - 1)]
        self._idx += 1
        return ChatResponse(content=reply, finish_reason=FinishReason.STOP)

    async def chat_stream(self, messages: list[Message], **kwargs: Any) -> AsyncIterator[str]:
        yield "stub"


class FailingLLM(FakeLLM):
    async def chat(self, messages: list[Message], **kwargs: Any) -> ChatResponse:
        raise RuntimeError("LLM unavailable")


def _make_conversation(n: int, words_per_msg: int = 30) -> list[Message]:
    return [_msg("user", f"message {i} " + "word " * words_per_msg) for i in range(n)]


class TestRollingSummarizeFirstPass:
    async def test_first_compress_produces_summary_marker(self):
        llm = FakeLLM(replies=["summary of early conversation"])
        strategy = RollingSummarizeStrategy(llm, recent_keep=2)
        messages = [Message(role="system", content="system prompt")] + _make_conversation(8)

        result = await strategy.compress(messages, 4000)

        summary_msgs = [m for m in result if m.text.startswith(_SUMMARY_MARKER)]
        assert len(summary_msgs) == 1
        assert "summary of early conversation" in summary_msgs[0].text

    async def test_first_compress_keeps_recent_messages(self):
        llm = FakeLLM(replies=["summary"])
        strategy = RollingSummarizeStrategy(llm, recent_keep=2)
        messages = _make_conversation(8)

        result = await strategy.compress(messages, 4000)

        kept_texts = [m.text for m in result if not m.text.startswith(_SUMMARY_MARKER)]
        assert len(kept_texts) == 2
        assert "message 6" in kept_texts[0]
        assert "message 7" in kept_texts[1]

    async def test_first_compress_sends_full_text_to_llm(self):
        llm = FakeLLM(replies=["summary"])
        strategy = RollingSummarizeStrategy(llm, recent_keep=2)
        messages = _make_conversation(6)

        await strategy.compress(messages, 4000)

        assert len(llm.chat_calls) == 1
        prompt_text = llm.chat_calls[0][0].text
        assert "message 0" in prompt_text
        assert "Summarize" in prompt_text


class TestRollingSummarizeIncremental:
    async def test_incremental_update_sends_existing_summary(self):
        llm = FakeLLM(replies=["summary v1", "summary v2"])
        strategy = RollingSummarizeStrategy(llm, recent_keep=2)

        msgs1 = _make_conversation(8)
        result1 = await strategy.compress(msgs1, 4000)

        new_msgs = result1 + _make_conversation(4)
        for m in _make_conversation(4):
            new_msgs.append(m)
        await strategy.compress(new_msgs, 4000)

        assert len(llm.chat_calls) == 2
        second_prompt = llm.chat_calls[1][0].text
        assert "Existing conversation summary" in second_prompt
        assert "summary v1" in second_prompt
        assert "New messages since last summary" in second_prompt

    async def test_marker_preserved_across_rounds(self):
        llm = FakeLLM(replies=["summary v1", "summary v2"])
        strategy = RollingSummarizeStrategy(llm, recent_keep=2)

        msgs1 = _make_conversation(8)
        result1 = await strategy.compress(msgs1, 4000)

        conv2 = list(result1) + _make_conversation(6)
        result2 = await strategy.compress(conv2, 4000)

        markers = [m for m in result2 if m.text.startswith(_SUMMARY_MARKER)]
        assert len(markers) == 1
        assert "summary v2" in markers[0].text


class TestRollingSummarizeCondensation:
    async def test_condense_triggered_when_summary_too_long(self):
        long_summary = "word " * 1000
        condensed = "condensed summary"
        llm = FakeLLM(replies=[long_summary, condensed])
        strategy = RollingSummarizeStrategy(llm, recent_keep=2, max_summary_tokens=200)

        messages = _make_conversation(8)
        result = await strategy.compress(messages, 4000)

        assert len(llm.chat_calls) == 2
        assert "Condense" in llm.chat_calls[1][0].text
        markers = [m for m in result if m.text.startswith(_SUMMARY_MARKER)]
        assert condensed in markers[0].text

    async def test_no_condense_when_summary_within_limit(self):
        short_summary = "brief summary"
        llm = FakeLLM(replies=[short_summary])
        strategy = RollingSummarizeStrategy(llm, recent_keep=2, max_summary_tokens=8000)

        messages = _make_conversation(8)
        await strategy.compress(messages, 4000)

        assert len(llm.chat_calls) == 1


class TestRollingSummarizeCondenseFailure:
    async def test_condense_failure_keeps_long_summary(self):
        long_summary = "word " * 1000

        class CondenseFailsLLM(FakeLLM):
            async def chat(self, messages, **kwargs):
                self.chat_calls.append(messages)
                if len(self.chat_calls) == 2:
                    raise RuntimeError("condense failed")
                return ChatResponse(content=long_summary, finish_reason=FinishReason.STOP)

        llm = CondenseFailsLLM()
        strategy = RollingSummarizeStrategy(llm, recent_keep=2, max_summary_tokens=200)

        messages = _make_conversation(8)
        result = await strategy.compress(messages, 4000)

        markers = [m for m in result if m.text.startswith(_SUMMARY_MARKER)]
        assert long_summary.strip() in markers[0].text


class TestRollingSummarizeFallback:
    async def test_falls_back_to_truncate_on_llm_failure(self):
        llm = FailingLLM()
        strategy = RollingSummarizeStrategy(llm, recent_keep=2)
        messages = _make_conversation(8)
        target = _total_tokens(messages) // 3

        result = await strategy.compress(messages, target)

        assert all(not m.text.startswith(_SUMMARY_MARKER) for m in result)
        assert _total_tokens(result) <= target + 50

    async def test_short_conversation_returns_unchanged(self):
        llm = FakeLLM()
        strategy = RollingSummarizeStrategy(llm, recent_keep=4)
        messages = _make_conversation(3)

        result = await strategy.compress(messages, 4000)

        assert result == messages
        assert len(llm.chat_calls) == 0


class TestRollingSummarizeSystemMessages:
    async def test_system_messages_preserved(self):
        llm = FakeLLM(replies=["summary"])
        strategy = RollingSummarizeStrategy(llm, recent_keep=2)
        messages = [
            Message(role="system", content="system prompt"),
            Message(role="system", content="another instruction"),
        ] + _make_conversation(6)

        result = await strategy.compress(messages, 4000)

        system_result = [m for m in result if m.role == "system" and not m.text.startswith(_SUMMARY_MARKER)]
        assert len(system_result) == 2


class TestGetStrategyRollingSummarize:
    def test_factory_creates_rolling_summarize(self):
        llm = FakeLLM()
        strategy = get_strategy("rolling_summarize", llm=llm)
        assert isinstance(strategy, RollingSummarizeStrategy)

    def test_factory_passes_max_summary_tokens(self):
        llm = FakeLLM()
        strategy = get_strategy("rolling_summarize", llm=llm, max_summary_tokens=500)
        assert strategy._max_summary_tokens == 500

    def test_factory_raises_without_llm(self):
        with pytest.raises(ValueError, match="RollingSummarizeStrategy"):
            get_strategy("rolling_summarize")

    def test_factory_unknown_name_raises(self):
        with pytest.raises(ValueError, match="Unknown"):
            get_strategy("nonexistent_strategy")


def _total_tokens(messages: list[Message]) -> int:
    return sum(estimate_tokens(m.text) for m in messages)
