"""Document indexer – chunk text and store to memory."""

from __future__ import annotations

import hashlib
import time
import uuid
from typing import Any

from mindbot.memory.storage import SQLiteStorage
from mindbot.memory.types import MemoryChunk, MemorySource, MemoryType
from mindbot.utils import get_logger

logger = get_logger("memory.indexer")


class MemoryIndexer:
    """Chunk and index documents into the memory storage.

    The indexer deduplicates by content hash so the same text is never stored
    twice.
    """

    def __init__(
        self,
        storage: SQLiteStorage,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
    ) -> None:
        self._storage = storage
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    def index_text(
        self,
        text: str,
        source: str | MemorySource = MemorySource.SHORT_TERM,
        memory_type: str | MemoryType = MemoryType.CONVERSATION,
        date: str | None = None,
        file_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> list[MemoryChunk]:
        """Split *text* into chunks and store."""
        chunks_text = self._split(text)
        source_value = MemoryChunk.parse_source(source)
        memory_type_value = MemoryChunk.parse_memory_type(memory_type)

        now = time.time()
        stored: list[MemoryChunk] = []
        for i, ct in enumerate(chunks_text):
            chunk = MemoryChunk(
                id=uuid.uuid4().hex,
                text=ct,
                source=source_value,
                memory_type=memory_type_value,
                date=date,
                created_at=now,
                updated_at=now,
                file_name=file_name,
                hash=hashlib.sha256(ct.encode()).hexdigest()[:16],
                metadata=metadata or {},
            )
            self._storage.insert(chunk)
            stored.append(chunk)

        return stored

    # ------------------------------------------------------------------
    # Text splitting
    # ------------------------------------------------------------------

    def _split(self, text: str) -> list[str]:
        """Naive character-level chunking with overlap."""
        if len(text) <= self._chunk_size:
            return [text]
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = start + self._chunk_size
            chunks.append(text[start:end])
            start = end - self._chunk_overlap
        return chunks
