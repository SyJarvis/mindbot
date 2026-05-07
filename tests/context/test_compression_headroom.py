from __future__ import annotations

from mindbot.config.schema import ContextConfig
from mindbot.context.compression import TruncateStrategy
from mindbot.context.manager import ContextManager
from mindbot.context.models import Message


def _msg(role: str, text: str, kind: str | None = None) -> Message:
    m = Message(role=role, content=text)
    if kind:
        m.message_kind = kind
    return m


def _total_tokens(messages: list[Message]) -> int:
    from mindbot.utils import estimate_tokens
    return sum(estimate_tokens(m.text) for m in messages)


class TestTruncateDropFirst:
    async def test_drops_tool_result_before_user_messages(self):
        strategy = TruncateStrategy()
        messages = [
            _msg("user", "hello " * 50),
            _msg("assistant", "hi " * 50, "assistant_tool_call"),
            _msg("tool", "result " * 80, "tool_result"),
            _msg("user", "next question " * 50),
        ]
        total_before = _total_tokens(messages)
        target = total_before // 2
        result = await strategy.compress(messages, target)

        remaining_kinds = [
            m.message_kind for m in result if m.message_kind
        ]
        assert "tool_result" not in remaining_kinds

    async def test_keeps_all_when_within_budget(self):
        strategy = TruncateStrategy()
        messages = [
            _msg("user", "short"),
            _msg("assistant", "reply"),
        ]
        target = _total_tokens(messages) + 1000
        result = await strategy.compress(messages, target)
        assert len(result) == 2

    async def test_phase2_truncates_oldest_after_dropping_low_value(self):
        strategy = TruncateStrategy()
        messages = [
            _msg("user", "old question " * 20),
            _msg("assistant", "old reply " * 20),
            _msg("tool", "old result " * 30, "tool_result"),
            _msg("user", "new question " * 20),
            _msg("assistant", "new reply " * 20),
        ]
        all_tokens = _total_tokens(messages)
        target = all_tokens // 3
        result = await strategy.compress(messages, target)

        result_texts = " ".join(m.text for m in result)
        assert "old result" not in result_texts

    async def test_preserves_system_messages(self):
        strategy = TruncateStrategy()
        messages = [
            Message(role="system", content="system prompt"),
            _msg("user", "hello " * 100),
        ]
        result = await strategy.compress(messages, 10)
        assert any(m.role == "system" for m in result)


class TestCompactTriggerAndTarget:
    async def test_compact_targets_ratio(self):
        ctx = ContextManager(
            ContextConfig(max_tokens=1000),
        )
        ctx._config.compression_config.compact_trigger_ratio = 0.8
        ctx._config.compression_config.compact_target_ratio = 0.4

        for i in range(100):
            ctx.add_conversation_message("user", f"message {i} " * 10)

        await ctx.compact()

        conv_tokens = ctx.get_block("conversation").token_count
        expected_max = int(1000 * 0.4)
        assert conv_tokens <= expected_max + 50

    async def test_compact_returns_token_count(self):
        ctx = ContextManager(
            ContextConfig(max_tokens=1000),
        )

        for i in range(50):
            ctx.add_conversation_message("user", f"message {i} " * 10)

        result = await ctx.compact()
        assert isinstance(result, int)
        assert result == ctx.get_block("conversation").token_count

    async def test_check_and_compact_defers_until_maybe_compact(self):
        ctx = ContextManager(
            ContextConfig(max_tokens=2000),
        )
        ctx._config.compression_config.compact_trigger_ratio = 0.5
        ctx._config.compression_config.compact_target_ratio = 0.2

        for i in range(200):
            ctx.add_conversation_message("user", f"msg {i} " * 5)

        assert ctx._needs_compaction is True

        await ctx.maybe_compact()

        conv_tokens = ctx.get_block("conversation").token_count
        expected_max = int(2000 * 0.2)
        assert conv_tokens <= expected_max + 50
        assert ctx._needs_compaction is False

    async def test_maybe_compact_returns_none_when_no_flag(self):
        ctx = ContextManager(
            ContextConfig(max_tokens=10000),
        )

        result = await ctx.maybe_compact()
        assert result is None

    def test_no_compact_below_trigger(self):
        ctx = ContextManager(
            ContextConfig(max_tokens=10000),
        )
        ctx._config.compression_config.compact_trigger_ratio = 0.8
        ctx._config.compression_config.compact_target_ratio = 0.4

        for i in range(5):
            ctx.add_conversation_message("user", f"msg {i}")

        conv_tokens = ctx.get_block("conversation").token_count
        trigger = 10000 * 0.8
        assert conv_tokens < trigger
        assert ctx._needs_compaction is False
