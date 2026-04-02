"""Memory compaction – purge or summarize old short-term memories."""

from __future__ import annotations

import time

from src.mindbot.memory.storage import SQLiteStorage
from src.mindbot.utils import get_logger

logger = get_logger("memory.compaction")


class MemoryCompactor:
    """Handles periodic compaction of the short-term memory store."""

    def __init__(self, storage: SQLiteStorage, retention_days: int = 7) -> None:
        self._storage = storage
        self._retention_days = retention_days

    @property
    def retention_days(self) -> int:
        return self._retention_days

    def purge_expired(self) -> int:
        """Delete short-term memories older than the retention window.

        Returns the number of chunks deleted.
        """
        cutoff = time.time() - (self._retention_days * 86_400)
        count = self._storage.delete_older_than(cutoff, source="short_term")
        if count:
            logger.info("Purged %d expired short-term memory chunks", count)
        return count
