from __future__ import annotations

from pathlib import Path

from mindbot.config.schema import Config, ModelConfig
from mindbot.context.models import ImagePart, TextPart
from mindbot.multimodal.models import ContentInput, ContentItem, MediaType


def test_model_config_vision_role_sets_vision_flag() -> None:
    model = ModelConfig(id="qwen-vl", role="vision")

    assert model.vision is True


def test_mindbot_prepares_images_for_chat(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    from mindbot import MindBot

    bot = MindBot(config=Config())
    content = bot._prepare_message_content("what is this?", images=[b"image-bytes"])

    assert isinstance(content, list)
    assert isinstance(content[0], TextPart)
    assert isinstance(content[1], ImagePart)


def test_mindbot_prepares_content_input(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    from mindbot import MindBot

    bot = MindBot(config=Config())
    message = ContentInput(
        text="describe",
        images=[ContentItem(type=MediaType.IMAGE, source=b"image-bytes")],
    )
    content = bot._prepare_message_content(message)

    assert isinstance(content, list)
    assert isinstance(content[0], TextPart)
    assert isinstance(content[1], ImagePart)
