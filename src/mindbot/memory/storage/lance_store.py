"""LanceDB vector store implementation."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import lancedb
import numpy as np
import pyarrow as pa

from mindbot.memory.storage.vector_store import SearchResult, VectorStore
from mindbot.utils import get_logger

logger = get_logger("memory.lance_store")

# LanceDB schema
SCHEMA = pa.schema([
    pa.field("shard_id", pa.utf8()),
    pa.field("vector", pa.list_(pa.float32())),
    pa.field("text", pa.utf8()),           # Store summary for FTS
    pa.field("cluster_id", pa.utf8()),
    pa.field("chunk_id", pa.utf8()),
    pa.field("shard_type", pa.utf8()),
    pa.field("created_at", pa.float64()),
    pa.field("updated_at", pa.float64()),
])


class LanceVectorStore(VectorStore):
    """LanceDB-based vector store with FTS support."""

    def __init__(
        self,
        uri: str = "~/.mindbot/vectors",
        table_name: str = "memory_vectors",
        dimension: int = 512,
    ) -> None:
        self._uri = str(Path(uri).expanduser())
        self._table_name = table_name
        self._dimension = dimension
        self._db = lancedb.connect(self._uri)
        self._schema = pa.schema([
            pa.field("shard_id", pa.utf8()),
            pa.field("vector", pa.list_(pa.float32(), dimension)),
            pa.field("text", pa.utf8()),
            pa.field("cluster_id", pa.utf8()),
            pa.field("chunk_id", pa.utf8()),
            pa.field("shard_type", pa.utf8()),
            pa.field("created_at", pa.float64()),
            pa.field("updated_at", pa.float64()),
        ])
        self._table = self._open_or_create_table()
        self._fts_created = False

    def _open_or_create_table(self) -> lancedb.db.LanceTable | Any:
        """Open existing table or create new one."""
        if self._table_name in self._db.table_names():
            return self._db.open_table(self._table_name)
        return self._db.create_table(
            self._table_name,
            schema=self._schema,
        )

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def insert(self, shard_id: str, vector: list[float], metadata: dict | None = None) -> None:
        """Insert a vector with metadata."""
        md = metadata or {}
        now = time.time()
        data = [{
            "shard_id": shard_id,
            "vector": np.array(vector, dtype=np.float32).tolist(),
            "text": md.get("summary", ""),
            "cluster_id": md.get("cluster_id", ""),
            "chunk_id": md.get("chunk_id", ""),
            "shard_type": md.get("shard_type", "fact"),
            "created_at": now,
            "updated_at": now,
        }]
        self._table.add(data)
        self._ensure_fts()
        logger.debug(f"Inserted vector for shard {shard_id}")

    def insert_batch(self, items: list[tuple[str, list[float], dict | None]]) -> None:
        """Insert multiple vectors at once."""
        now = time.time()
        data = []
        for shard_id, vector, metadata in items:
            md = metadata or {}
            data.append({
                "shard_id": shard_id,
                "vector": np.array(vector, dtype=np.float32).tolist(),
                "text": md.get("summary", ""),
                "cluster_id": md.get("cluster_id", ""),
                "chunk_id": md.get("chunk_id", ""),
                "shard_type": md.get("shard_type", "fact"),
                "created_at": now,
                "updated_at": now,
            })
        if data:
            self._table.add(data)
            self._ensure_fts()
            logger.debug(f"Batch inserted {len(data)} vectors")

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        vector: list[float],
        top_k: int = 10,
        filter_expr: str | None = None,
    ) -> list[SearchResult]:
        """Search by vector similarity."""
        query = np.array(vector, dtype=np.float32)
        builder = self._table.search(query, vector_column_name="vector").limit(top_k).metric("cosine")

        if filter_expr:
            builder = builder.where(filter_expr, prefilter=True)

        results = builder.to_pandas()

        search_results = []
        for _, row in results.iterrows():
            search_results.append(SearchResult(
                shard_id=row["shard_id"],
                score=float(1.0 - row["_distance"]),  # Convert distance to similarity
                distance=float(row["_distance"]),
            ))
        return search_results

    def search_by_text(
        self,
        query: str,
        top_k: int = 10,
        filter_expr: str | None = None,
    ) -> list[SearchResult]:
        """Full-text search using LanceDB FTS."""
        self._ensure_fts()

        builder = self._table.search(query).limit(top_k)

        if filter_expr:
            builder = builder.where(filter_expr, prefilter=True)

        try:
            results = builder.to_pandas()
        except Exception:
            return []

        search_results = []
        for _, row in results.iterrows():
            search_results.append(SearchResult(
                shard_id=row["shard_id"],
                score=float(row.get("_relevance_score", 0.0)),
                distance=0.0,
            ))
        return search_results

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def delete(self, shard_id: str) -> None:
        """Delete by shard ID."""
        self._table.delete(f'shard_id = "{shard_id}"')
        logger.debug(f"Deleted vector for shard {shard_id}")

    def update(self, shard_id: str, new_vector: list[float], metadata: dict | None = None) -> None:
        """Update vector and metadata for a shard."""
        md = metadata or {}
        values: dict[str, Any] = {
            "vector": np.array(new_vector, dtype=np.float32).tolist(),
            "updated_at": time.time(),
        }
        if "summary" in md:
            values["text"] = md["summary"]
        if "cluster_id" in md:
            values["cluster_id"] = md["cluster_id"]
        if "chunk_id" in md:
            values["chunk_id"] = md["chunk_id"]

        self._table.update(
            where=f'shard_id = "{shard_id}"',
            values=values,
        )
        logger.debug(f"Updated vector for shard {shard_id}")

    def get_vector(self, shard_id: str) -> list[float] | None:
        """Get vector by shard ID."""
        results = self._table.search().where(f'shard_id = "{shard_id}"').limit(1).to_pandas()
        if results.empty:
            return None
        vec = results.iloc[0]["vector"]
        return vec.tolist() if hasattr(vec, "tolist") else list(vec)

    def count(self) -> int:
        """Total number of vectors."""
        return len(self._table)

    # ------------------------------------------------------------------
    # Index Management
    # ------------------------------------------------------------------

    def create_vector_index(self) -> None:
        """Create IVF-PQ vector index for faster ANN search."""
        if self.count() < 100:
            logger.debug("Too few vectors for index creation, skipping")
            return
        try:
            self._table.create_index(
                metric="cosine",
                vector_column_name="vector",
            )
            logger.info(f"Created vector index on {self.count()} vectors")
        except Exception as e:
            logger.warning(f"Failed to create vector index: {e}")

    def _ensure_fts(self) -> None:
        """Ensure FTS index exists for full-text search."""
        if self._fts_created:
            return
        try:
            self._table.create_fts_index("text", replace=False)
            self._fts_created = True
            logger.debug("Created FTS index on text column")
        except Exception:
            # FTS index may already exist
            self._fts_created = True

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the store."""
        # LanceDB doesn't require explicit close
        pass