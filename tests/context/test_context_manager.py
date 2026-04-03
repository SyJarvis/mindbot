from __future__ import annotations

from mindbot.config.schema import ContextConfig
from mindbot.context.compression import TruncateStrategy
from mindbot.context.manager import ContextManager


def test_context_manager_uses_truncate_on_unified_main_path():
    ctx = ContextManager(ContextConfig(compression="summarize"))

    assert isinstance(ctx._strategy, TruncateStrategy)


def test_context_manager_exposes_intent_state_block_in_order():
    ctx = ContextManager(ContextConfig(max_tokens=4000))
    ctx.set_system_identity("system")
    ctx.set_skills_overview("overview")
    ctx.set_skills_detail("detail")
    ctx.add_conversation_message("user", "earlier")
    ctx.set_intent_state("intent")

    assert ctx.block_names == [
        "system_identity",
        "skills_overview",
        "skills_detail",
        "memory",
        "conversation",
        "intent_state",
        "user_input",
    ]
    assert ctx.get_block("skills_overview").messages[0].content == "overview"
    assert ctx.get_block("skills_detail").messages[0].content == "detail"
    assert ctx.get_block("intent_state").messages[0].content == "intent"

