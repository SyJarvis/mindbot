"""MediaProcessor — normalises various image sources into ``ImagePart``."""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

from mindbot.context.models import ImagePart, TextPart
from mindbot.multimodal.models import ContentItem, MediaSource, MediaType
from mindbot.utils import get_logger

logger = get_logger("multimodal.processor")

# Upper bounds applied *before* any network/disk IO.
_DEFAULT_MAX_IMAGES = 10
_DEFAULT_MAX_FILE_SIZE_MB = 20


class MediaProcessor:
    """Convert user-supplied media sources into canonical ``ImagePart`` objects.

    Supported source kinds:
    - HTTP(S) URL  — kept as-is (providers handle remote fetch)
    - Local file path — read + base64-encode
    - Raw ``bytes``  — base64-encode
    - Base64 string  — passed through
    """

    def __init__(
        self,
        *,
        max_images: int = _DEFAULT_MAX_IMAGES,
        max_file_size_mb: float = _DEFAULT_MAX_FILE_SIZE_MB,
    ) -> None:
        self._max_images = max_images
        self._max_file_size_bytes = int(max_file_size_mb * 1024 * 1024)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_images(
        self,
        sources: list[MediaSource],
        default_mime: str = "image/png",
    ) -> list[ImagePart]:
        """Convert a list of raw media sources to ``ImagePart`` objects."""
        if len(sources) > self._max_images:
            raise ValueError(
                f"Too many images ({len(sources)}); limit is {self._max_images}"
            )
        return [self._process_single(src, default_mime) for src in sources]

    def process_content_items(self, items: list[ContentItem]) -> list[ImagePart]:
        """Convert ``ContentItem`` objects (from ``ContentInput``) to ``ImagePart``."""
        if len(items) > self._max_images:
            raise ValueError(
                f"Too many images ({len(items)}); limit is {self._max_images}"
            )
        results: list[ImagePart] = []
        for item in items:
            if item.type is not MediaType.IMAGE:
                raise NotImplementedError(
                    f"Media type {item.type.value!r} is not yet supported"
                )
            results.append(self._process_single(item.source, item.mime_type))
        return results

    def build_message_content(
        self,
        text: str,
        image_parts: list[ImagePart],
    ) -> str | list[TextPart | ImagePart]:
        """Build the ``MessageContent`` value for a ``Message``.

        Returns plain ``str`` when there are no images (preserving the
        existing pure-text path) or a multimodal part list otherwise.
        """
        if not image_parts:
            return text
        parts: list[TextPart | ImagePart] = [TextPart(text=text)]
        parts.extend(image_parts)
        return parts

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _process_single(self, source: MediaSource, mime_type: str) -> ImagePart:
        if isinstance(source, bytes):
            self._check_size(len(source), "<bytes>")
            return ImagePart(
                data=base64.b64encode(source).decode(),
                mime_type=mime_type,
            )

        if isinstance(source, str):
            if source.startswith(("http://", "https://")):
                return ImagePart(data=source, mime_type=mime_type)

            path = Path(source)
            if path.is_file():
                return self._load_from_file(path, mime_type)

            # Assume base64 string
            return ImagePart(data=source, mime_type=mime_type)

        raise TypeError(f"Unsupported media source type: {type(source)}")

    def _load_from_file(self, path: Path, fallback_mime: str) -> ImagePart:
        data = path.read_bytes()
        self._check_size(len(data), str(path))
        mime = mimetypes.guess_type(str(path))[0] or fallback_mime
        return ImagePart(
            data=base64.b64encode(data).decode(),
            mime_type=mime,
        )

    def _check_size(self, size: int, label: str) -> None:
        if size > self._max_file_size_bytes:
            mb = size / (1024 * 1024)
            limit_mb = self._max_file_size_bytes / (1024 * 1024)
            raise ValueError(
                f"Media {label!r} is {mb:.1f} MB; limit is {limit_mb:.0f} MB"
            )
