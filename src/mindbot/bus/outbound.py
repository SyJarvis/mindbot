"""Helpers for turning agent responses into outbound bus messages."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.mindbot.agent.models import AgentResponse
from src.mindbot.bus.events import OutboundMessage

OUTBOUND_MESSAGE_METADATA_KEY = "outbound_message"


def build_outbound_message(
    *,
    channel: str,
    chat_id: str,
    response: AgentResponse,
) -> OutboundMessage:
    """Build an outbound bus message from an agent response.

    The attachment contract is intentionally narrow and explicit:

    ``response.metadata["outbound_message"]`` may contain a mapping with:
    - ``content``: optional text override
    - ``media``: list of local file paths to send as channel attachments
    - ``reply_to``: optional reply target for channels that support it
    - ``metadata``: optional channel-specific outbound metadata
    """

    spec = _normalize_outbound_spec(response.metadata.get(OUTBOUND_MESSAGE_METADATA_KEY))

    content = spec.get("content", response.content)
    reply_to = spec.get("reply_to")
    media = _normalize_media(spec.get("media"))
    outbound_metadata = spec.get("metadata")

    return OutboundMessage(
        channel=channel,
        chat_id=chat_id,
        content=content if isinstance(content, str) else response.content,
        reply_to=reply_to if isinstance(reply_to, str) and reply_to else None,
        media=media,
        metadata=outbound_metadata if isinstance(outbound_metadata, dict) else {},
    )


def _normalize_outbound_spec(spec: Any) -> dict[str, Any]:
    if not isinstance(spec, Mapping):
        return {}
    return dict(spec)


def _normalize_media(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    return []
