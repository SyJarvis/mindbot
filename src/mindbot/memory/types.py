"""Data types for the memory subsystem."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MemorySource(str, Enum):
    """Memory source (lifecycle tier)."""

    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    FACT = "fact"


class MemoryType(str, Enum):
    """Memory content type."""

    CONVERSATION = "conversation"
    SUMMARY = "summary"
    FACT = "fact"
    EXTRACT = "extract"


@dataclass
class MemoryChunk:
    """A single piece of stored memory."""

    id: str
    text: str
    source: MemorySource = MemorySource.SHORT_TERM
    memory_type: MemoryType = MemoryType.CONVERSATION
    date: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    file_name: str | None = None
    hash: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def parse_source(cls, value: str | MemorySource) -> MemorySource:
        if isinstance(value, MemorySource):
            return value
        try:
            return MemorySource(value)
        except Exception:
            return MemorySource.SHORT_TERM

    @classmethod
    def parse_memory_type(cls, value: str | MemoryType) -> MemoryType:
        if isinstance(value, MemoryType):
            return value
        try:
            return MemoryType(value)
        except Exception:
            return MemoryType.CONVERSATION
