"""Checkpoint mechanism for conversation context."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from src.mindbot.context.models import Message


@dataclass
class Checkpoint:
    """Snapshot of the conversation state at a point in time."""

    id: str
    name: str
    messages: list[Message] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
