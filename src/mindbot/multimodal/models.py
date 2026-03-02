"""User-facing multimodal input types.

These are *input DTOs* — they describe what the user passes in.
Internally they are converted to the canonical ``TextPart`` / ``ImagePart``
representation that providers already understand.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Union


class MediaType(str, Enum):
    """Supported media modalities (image-only for now; audio/video reserved)."""

    IMAGE = "image"
    AUDIO = "audio"   # reserved
    VIDEO = "video"   # reserved


# URL string, local file path, base64 string, or raw bytes.
MediaSource = Union[str, bytes]


@dataclass
class ContentItem:
    """A single media attachment with its type and MIME metadata."""

    type: MediaType
    source: MediaSource
    mime_type: str = "image/png"


@dataclass
class ContentInput:
    """Unified multimodal input for ``Mindbot.chat`` / ``Mindbot.chat_stream``.

    Users may pass this directly when they need full control over media
    metadata.  For the common case a simple ``images=[...]`` shorthand is
    also available on the chat methods.
    """

    text: str
    images: list[ContentItem] = field(default_factory=list)
    # Reserved for future modalities:
    # audio: list[ContentItem] = field(default_factory=list)
    # video: list[ContentItem] = field(default_factory=list)
