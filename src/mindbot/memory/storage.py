"""SQLite-backed storage for memory chunks."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from mindbot.memory.types import MemoryChunk
from mindbot.utils import get_logger

logger = get_logger("memory.storage")


class SQLiteStorage:
    """Persistent storage for memory chunks backed by SQLite."""

    def __init__(
        self,
        db_path: str = "./data/memory.db",
        *,
        enable_fts: bool = True,
    ) -> None:
        self._db_path = str(Path(db_path).expanduser())
        self._conn: sqlite3.Connection | None = None
        self._enable_fts = enable_fts
        self._fts_available = False

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _ensure_db(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn

        os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()
        self._migrate_schema()
        self._create_indexes()
        self._init_fts()
        self._conn.commit()
        return self._conn

    def _create_tables(self) -> None:
        assert self._conn is not None
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS memory_chunks (
                id          TEXT PRIMARY KEY,
                text        TEXT NOT NULL,
                source      TEXT NOT NULL DEFAULT 'short_term',
                date        TEXT,
                chunk_type  TEXT NOT NULL DEFAULT 'conversation',
                hash        TEXT NOT NULL,
                metadata    TEXT NOT NULL DEFAULT '{}',
                created_at  REAL NOT NULL,
                updated_at  REAL NOT NULL,
                file_name   TEXT,
                embedding   BLOB
            );
            """
        )

    def _migrate_schema(self) -> None:
        assert self._conn is not None
        cols = self._table_columns("memory_chunks")
        migration_steps = [
            ("date", "ALTER TABLE memory_chunks ADD COLUMN date TEXT"),
            (
                "chunk_type",
                "ALTER TABLE memory_chunks ADD COLUMN chunk_type TEXT NOT NULL DEFAULT 'conversation'",
            ),
            (
                "updated_at",
                "ALTER TABLE memory_chunks ADD COLUMN updated_at REAL NOT NULL DEFAULT 0",
            ),
            ("file_name", "ALTER TABLE memory_chunks ADD COLUMN file_name TEXT"),
        ]
        for col_name, sql in migration_steps:
            if col_name not in cols:
                self._conn.execute(sql)

        self._conn.execute(
            """
            UPDATE memory_chunks
            SET updated_at = created_at
            WHERE updated_at IS NULL OR updated_at = 0
            """
        )

    def _create_indexes(self) -> None:
        assert self._conn is not None
        self._conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_source ON memory_chunks(source);
            CREATE INDEX IF NOT EXISTS idx_date ON memory_chunks(date);
            CREATE INDEX IF NOT EXISTS idx_created_at ON memory_chunks(created_at);
            CREATE INDEX IF NOT EXISTS idx_source_date ON memory_chunks(source, date);
            """
        )

    def _init_fts(self) -> None:
        assert self._conn is not None
        if not self._enable_fts:
            return
        try:
            self._conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts
                USING fts5(
                    id UNINDEXED,
                    text,
                    source UNINDEXED,
                    tokenize='porter unicode61'
                )
                """
            )
            self._fts_available = True
        except sqlite3.DatabaseError as exc:
            logger.warning("FTS5 unavailable; fallback to LIKE search (%s)", exc)
            self._fts_available = False

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def insert(self, chunk: MemoryChunk) -> None:
        """Insert a memory chunk. Duplicates (by hash) are silently ignored."""
        conn = self._ensure_db()
        if not chunk.id:
            chunk.id = uuid.uuid4().hex
        if not chunk.hash:
            chunk.hash = hashlib.sha256(chunk.text.encode()).hexdigest()[:16]
        chunk.source = MemoryChunk.parse_source(chunk.source)
        chunk.memory_type = MemoryChunk.parse_memory_type(chunk.memory_type)

        now = time.time()
        if not chunk.created_at:
            chunk.created_at = now
        if not chunk.updated_at:
            chunk.updated_at = chunk.created_at

        conn.execute(
            """
            INSERT OR IGNORE INTO memory_chunks
                (id, text, source, date, chunk_type, hash, metadata, created_at, updated_at, file_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chunk.id,
                chunk.text,
                chunk.source.value,
                chunk.date,
                chunk.memory_type.value,
                chunk.hash,
                json.dumps(chunk.metadata),
                chunk.created_at,
                chunk.updated_at,
                chunk.file_name,
            ),
        )
        if self._fts_available:
            self._upsert_fts(chunk)
        conn.commit()

    def search_fts(
        self,
        query: str,
        top_k: int = 10,
        source: str | None = None,
    ) -> list[MemoryChunk]:
        """FTS5 search; falls back to LIKE search when FTS is unavailable."""
        if not self._fts_available:
            return self.search_by_keyword(query, top_k=top_k, source=source)
        conn = self._ensure_db()
        params: list[Any] = [query]
        sql = (
            "SELECT c.* "
            "FROM memory_fts f "
            "JOIN memory_chunks c ON c.id = f.id "
            "WHERE memory_fts MATCH ?"
        )
        if source:
            sql += " AND c.source = ?"
            params.append(source)
        sql += " ORDER BY bm25(memory_fts) LIMIT ?"
        params.append(top_k)
        try:
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_chunk(r) for r in rows]
        except sqlite3.DatabaseError:
            return self.search_by_keyword(query, top_k=top_k, source=source)

    def search_by_keyword(
        self,
        query: str,
        top_k: int = 10,
        source: str | None = None,
    ) -> list[MemoryChunk]:
        """Naive keyword search (LIKE %keyword%)."""
        conn = self._ensure_db()
        sql = "SELECT * FROM memory_chunks WHERE text LIKE ?"
        params: list[Any] = [f"%{query}%"]
        if source:
            sql += " AND source = ?"
            params.append(source)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(top_k)
        rows = conn.execute(sql, params).fetchall()
        return [self._row_to_chunk(r) for r in rows]

    def get_all(self, source: str | None = None, limit: int = 100) -> list[MemoryChunk]:
        conn = self._ensure_db()
        sql = "SELECT * FROM memory_chunks"
        params: list[Any] = []
        if source:
            sql += " WHERE source = ?"
            params.append(source)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [self._row_to_chunk(r) for r in rows]

    def get_by_date(self, date: str, source: str = "short_term") -> list[MemoryChunk]:
        """Get chunks by date partition (YYYY-MM-DD)."""
        conn = self._ensure_db()
        rows = conn.execute(
            """
            SELECT * FROM memory_chunks
            WHERE source = ? AND date = ?
            ORDER BY created_at DESC
            """,
            (source, date),
        ).fetchall()
        return [self._row_to_chunk(r) for r in rows]

    def delete_older_than(self, cutoff: float, source: str = "short_term") -> int:
        """Delete chunks older than *cutoff* (epoch seconds). Returns count deleted."""
        conn = self._ensure_db()
        ids = conn.execute(
            "SELECT id FROM memory_chunks WHERE source = ? AND created_at < ?",
            (source, cutoff),
        ).fetchall()
        deleted_ids = [row["id"] for row in ids]
        cur = conn.execute(
            "DELETE FROM memory_chunks WHERE source = ? AND created_at < ?",
            (source, cutoff),
        )
        if deleted_ids:
            if self._fts_available:
                conn.executemany("DELETE FROM memory_fts WHERE id = ?", [(cid,) for cid in deleted_ids])
        conn.commit()
        return cur.rowcount

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _upsert_fts(self, chunk: MemoryChunk) -> None:
        assert self._conn is not None
        self._conn.execute("DELETE FROM memory_fts WHERE id = ?", (chunk.id,))
        self._conn.execute(
            "INSERT INTO memory_fts(id, text, source) VALUES (?, ?, ?)",
            (chunk.id, chunk.text, chunk.source.value),
        )

    def _table_columns(self, table_name: str) -> set[str]:
        assert self._conn is not None
        rows = self._conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {row[1] for row in rows}

    @staticmethod
    def _row_to_chunk(row: sqlite3.Row) -> MemoryChunk:
        return MemoryChunk(
            id=row["id"],
            text=row["text"],
            source=MemoryChunk.parse_source(row["source"]),
            memory_type=MemoryChunk.parse_memory_type(row["chunk_type"]),
            date=row["date"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            file_name=row["file_name"],
            hash=row["hash"],
            metadata=json.loads(row["metadata"]),
        )
