"""Tests for MindBot SYSTEM.md boot-time injection.

Covers:
- system prompt loaded from SYSTEM.md into config.agent.system_prompt
- missing SYSTEM.md uses built-in default
- empty SYSTEM.md results in empty string
- prompt reaches Scheduler assembly (system role message present)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch


def _setup_workspace(root: Path, system_md: str | None = None, settings: str | None = None) -> None:
    """Create a minimal ~/.mindbot workspace."""
    root.mkdir(parents=True, exist_ok=True)
    if settings is not None:
        (root / "settings.json").write_text(settings, encoding="utf-8")
    else:
        (root / "settings.json").write_text(
            '{"agent": {"model": "openai/test"}}', encoding="utf-8"
        )
    if system_md is not None:
        (root / "SYSTEM.md").write_text(system_md, encoding="utf-8")


# ------------------------------------------------------------------
# Injection tests
# ------------------------------------------------------------------

def test_system_prompt_injected(tmp_path, monkeypatch):
    """SYSTEM.md content ends up in config.agent.system_prompt."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

    root = fake_home / ".mindbot"
    _setup_workspace(root, system_md="You are helpful.")

    from mindbot.bot import MindBot

    fake_llm = type("FakeLLM", (), {
        "chat": None, "chat_stream": None, "bind_tools": lambda s, t: s,
        "get_info": lambda s: None, "get_model_list": lambda s: [],
    })()

    with patch("mindbot.providers.factory.ProviderFactory.create", return_value=fake_llm):
        bot = MindBot()

    assert bot.config.agent.system_prompt == "You are helpful."


def test_system_prompt_missing_ok(tmp_path, monkeypatch):
    """Missing SYSTEM.md uses the built-in default prompt."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

    _setup_workspace(fake_home / ".mindbot")

    fake_llm = type("FakeLLM", (), {
        "chat": None, "chat_stream": None, "bind_tools": lambda s, t: s,
        "get_info": lambda s: None, "get_model_list": lambda s: [],
    })()

    with patch("mindbot.providers.factory.ProviderFactory.create", return_value=fake_llm):
        from mindbot.bot import MindBot
        bot = MindBot()

    assert "MindBot" in bot.config.agent.system_prompt
    system_file = fake_home / ".mindbot" / "SYSTEM.md"
    assert not system_file.exists()


def test_system_prompt_empty_file_ok(tmp_path, monkeypatch):
    """Empty SYSTEM.md is allowed (empty system prompt, no crash)."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

    root = fake_home / ".mindbot"
    _setup_workspace(root, system_md="")

    from mindbot.bot import MindBot

    fake_llm = type("FakeLLM", (), {
        "chat": None, "chat_stream": None, "bind_tools": lambda s, t: s,
        "get_info": lambda s: None, "get_model_list": lambda s: [],
    })()

    with patch("mindbot.providers.factory.ProviderFactory.create", return_value=fake_llm):
        bot = MindBot()

    assert bot.config.agent.system_prompt == ""


# ------------------------------------------------------------------
# Integration: prompt reaches Scheduler
# ------------------------------------------------------------------

# def test_prompt_reaches_scheduler(tmp_path, monkeypatch):
#     """Injected system prompt appears in Scheduler-assembled messages."""
#     fake_home = tmp_path / "home"
#     fake_home.mkdir()
#     monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

#     root = fake_home / ".mindbot"
#     _setup_workspace(root, system_md="I am test bot.")

#     from mindbot.bot import MindBot
#     from mindbot.agent.scheduler import Scheduler

#     fake_llm = type("FakeLLM", (), {
#         "chat": None, "chat_stream": None, "bind_tools": lambda s, t: s,
#         "get_info": lambda s: None, "get_model_list": lambda s: [],
#     })()

#     with patch("mindbot.providers.factory.ProviderFactory.create", return_value=fake_llm):
#         bot = MindBot()

#     # _get_session_scheduler now lives on the base Agent, not MindAgent
#     scheduler = bot._agent._main_agent._get_session_scheduler("test")
#     messages = scheduler.assemble("hello")

#     system_msgs = [m for m in messages if m.role == "system"]
#     assert len(system_msgs) >= 1
#     assert system_msgs[0].text == "I am test bot."
