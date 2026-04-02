"""MemoryManager – unified entry point for the dual-memory system."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from src.mindbot.memory.compaction import MemoryCompactor
from src.mindbot.memory.indexer import MemoryIndexer
from src.mindbot.memory.markdown import MarkdownStorage
from src.mindbot.memory.searcher import HybridSearcher
from src.mindbot.memory.storage import SQLiteStorage
from src.mindbot.memory.types import MemoryChunk, MemorySource, MemoryType
from src.mindbot.utils import get_logger

logger = get_logger("memory.manager")


class MemoryManager:
    """Dual-memory system: short-term (ephemeral) + long-term (persistent).

    Provides a single façade over indexing, searching, and compaction.
    """

    def __init__(
        self,
        storage_path: str = "./data/memory.db",
        markdown_path: str = "~/.Mindbot/data/memory",
        short_term_retention_days: int = 7,
        enable_fts: bool = True,
    ) -> None:
        self._storage = SQLiteStorage(
            storage_path,
            enable_fts=enable_fts,
        )
        self._markdown = MarkdownStorage(markdown_path)
        self._indexer = MemoryIndexer(self._storage)
        self._searcher = HybridSearcher(self._storage)
        self._compactor = MemoryCompactor(self._storage, short_term_retention_days)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def append_to_short_term(
        self, content: str, metadata: dict[str, Any] | None = None,
    ) -> list[MemoryChunk]:
        """Store *content* as short-term memory."""
        md = metadata.copy() if metadata else {}
        date = datetime.now().strftime("%Y-%m-%d")
        file_name = f"{date}.md"
        md.setdefault("location", "unknown")
        md.setdefault("file_name", file_name)
        md.setdefault("date", date)
        chunks = self._indexer.index_text(
            content,
            source=MemorySource.SHORT_TERM,
            memory_type=MemoryType.CONVERSATION,
            date=date,
            file_name=file_name,
            metadata=md,
        )
        self._markdown.write_short_term(date, content, metadata=md)
        return chunks

    def promote_to_long_term(
        self, content: str, metadata: dict[str, Any] | None = None,
    ) -> list[MemoryChunk]:
        """Store *content* as long-term (persistent) memory."""
        md = metadata.copy() if metadata else {}
        file_name = str(md.get("file_name", "MEMORY.md"))
        md.setdefault("location", "unknown")
        md["file_name"] = file_name
        chunks = self._indexer.index_text(
            content,
            source=MemorySource.LONG_TERM,
            memory_type=MemoryType.FACT,
            file_name=file_name,
            metadata=md,
        )
        self._markdown.write_long_term(file_name, content, metadata=md)
        return chunks

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        top_k: int = 5,
        source: str | None = None,
    ) -> list[MemoryChunk]:
        """Hybrid search across the memory store."""
        return self._searcher.search(query, top_k=top_k, source=source)

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def compact(self) -> int:
        """Purge expired short-term memories. Returns count deleted."""
        deleted = self._compactor.purge_expired()
        cutoff_date = (datetime.now() - timedelta(days=self._compactor.retention_days)).strftime("%Y-%m-%d")
        self._markdown.delete_short_term_before(cutoff_date)
        return deleted

    def close(self) -> None:
        """Release resources."""
        self._storage.close()
