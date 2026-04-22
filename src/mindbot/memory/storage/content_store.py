"""Markdown content store - primary storage for full memory text content."""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any

from mindbot.utils import get_logger

logger = get_logger("memory.content_store")


class MarkdownContentStore:
    """
    Markdown primary storage - stores full memory content.

    Human-readable, editable, and serves as the source of truth for text content.
    """

    def __init__(self, base_path: str = "~/.mindbot/memory/content") -> None:
        self._base_path = Path(base_path).expanduser()
        self._shards_dir = self._base_path / "shards"
        self._chunks_dir = self._base_path / "chunks"
        self._clusters_dir = self._base_path / "clusters"
        self._archive_dir = self._base_path / "archive"
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        """Ensure all directories exist."""
        self._shards_dir.mkdir(parents=True, exist_ok=True)
        self._chunks_dir.mkdir(parents=True, exist_ok=True)
        self._clusters_dir.mkdir(parents=True, exist_ok=True)
        self._archive_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Shard Content Operations
    # ------------------------------------------------------------------

    def write_shard(
        self,
        shard_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> Path:
        """
        Write a single shard's full content to a Markdown file.

        Returns the path to the written file.
        """
        file_path = self._shards_dir / f"{shard_id}.md"
        formatted = self._format_shard(shard_id, content, metadata)
        with file_path.open("w", encoding="utf-8") as f:
            f.write(formatted)
        logger.debug(f"Wrote shard {shard_id} to {file_path}")
        return file_path

    def read_shard(self, shard_id: str) -> str:
        """
        Read a shard's full content from Markdown file.

        Returns the text content only (no metadata).
        """
        file_path = self._shards_dir / f"{shard_id}.md"
        if not file_path.exists():
            logger.warning(f"Shard file not found: {file_path}")
            return ""
        return self._parse_shard_content(file_path)

    def update_shard(self, shard_id: str, new_content: str) -> None:
        """Update a shard's content (preserves metadata section)."""
        file_path = self._shards_dir / f"{shard_id}.md"
        if not file_path.exists():
            logger.warning(f"Shard file not found for update: {file_path}")
            return

        # Read existing to preserve metadata
        existing = file_path.read_text(encoding="utf-8")
        metadata = self._extract_metadata(existing)

        # Write updated content
        formatted = self._format_shard(shard_id, new_content, metadata)
        with file_path.open("w", encoding="utf-8") as f:
            f.write(formatted)
        logger.debug(f"Updated shard {shard_id}")

    def delete_shard(self, shard_id: str) -> None:
        """Delete a shard's Markdown file."""
        file_path = self._shards_dir / f"{shard_id}.md"
        if file_path.exists():
            file_path.unlink()
            logger.debug(f"Deleted shard {shard_id}")

    def archive_shard(self, shard_id: str) -> Path:
        """Move a shard to archive directory."""
        src_path = self._shards_dir / f"{shard_id}.md"
        dst_path = self._archive_dir / f"{shard_id}.md"
        if src_path.exists():
            shutil.move(str(src_path), str(dst_path))
            logger.debug(f"Archived shard {shard_id}")
        return dst_path

    def unarchive_shard(self, shard_id: str) -> Path:
        """Restore a shard from archive."""
        src_path = self._archive_dir / f"{shard_id}.md"
        dst_path = self._shards_dir / f"{shard_id}.md"
        if src_path.exists():
            shutil.move(str(src_path), str(dst_path))
            logger.debug(f"Unarchived shard {shard_id}")
        return dst_path

    def shard_exists(self, shard_id: str) -> bool:
        """Check if shard file exists."""
        return (self._shards_dir / f"{shard_id}.md").exists()

    def list_shard_ids(self) -> list[str]:
        """List all shard IDs from shard directory."""
        return [
            f.stem for f in self._shards_dir.glob("*.md")
            if f.is_file()
        ]

    # ------------------------------------------------------------------
    # Chunk Aggregate Operations
    # ------------------------------------------------------------------

    def write_chunk_aggregate(
        self,
        chunk_id: str,
        chunk_name: str,
        shards: list[tuple[str, str]],  # [(shard_id, content), ...]
        description: str = "",
    ) -> Path:
        """
        Write a chunk's aggregate Markdown file containing all its shards.

        Useful for human browsing and backup.
        """
        file_path = self._chunks_dir / f"{chunk_id}.md"
        formatted = self._format_chunk(chunk_id, chunk_name, shards, description)
        with file_path.open("w", encoding="utf-8") as f:
            f.write(formatted)
        logger.debug(f"Wrote chunk aggregate {chunk_id} with {len(shards)} shards")
        return file_path

    def read_chunk_aggregate(self, chunk_id: str) -> str:
        """Read a chunk's aggregate Markdown file."""
        file_path = self._chunks_dir / f"{chunk_id}.md"
        if not file_path.exists():
            return ""
        return file_path.read_text(encoding="utf-8")

    def delete_chunk_aggregate(self, chunk_id: str) -> None:
        """Delete a chunk's aggregate file."""
        file_path = self._chunks_dir / f"{chunk_id}.md"
        if file_path.exists():
            file_path.unlink()
            logger.debug(f"Deleted chunk aggregate {chunk_id}")

    # ------------------------------------------------------------------
    # Cluster Index Operations
    # ------------------------------------------------------------------

    def write_cluster_index(
        self,
        cluster_id: str,
        cluster_name: str,
        chunk_ids: list[str],
        description: str = "",
    ) -> Path:
        """Write a cluster's index Markdown file."""
        file_path = self._clusters_dir / f"{cluster_id}.md"
        formatted = self._format_cluster(cluster_id, cluster_name, chunk_ids, description)
        with file_path.open("w", encoding="utf-8") as f:
            f.write(formatted)
        logger.debug(f"Wrote cluster index {cluster_id}")
        return file_path

    # ------------------------------------------------------------------
    # Keyword Search (Grep-like)
    # ------------------------------------------------------------------

    def search_by_keyword(self, query: str, limit: int = 50) -> list[str]:
        """
        Search shards by keyword in content.

        Returns matching shard IDs.
        """
        query_lower = query.lower()
        matches = []
        for file_path in self._shards_dir.glob("*.md"):
            if not file_path.is_file():
                continue
            content = file_path.read_text(encoding="utf-8").lower()
            if query_lower in content:
                matches.append(file_path.stem)
            if len(matches) >= limit:
                break
        return matches

    def search_with_context(
        self,
        query: str,
        context_chars: int = 100,
        limit: int = 20,
    ) -> list[tuple[str, str]]:
        """
        Search shards with surrounding context.

        Returns [(shard_id, context_snippet), ...].
        """
        query_lower = query.lower()
        matches = []
        for file_path in self._shards_dir.glob("*.md"):
            if not file_path.is_file():
                continue
            content = file_path.read_text(encoding="utf-8")
            content_lower = content.lower()

            pos = content_lower.find(query_lower)
            if pos >= 0:
                # Get context around match
                start = max(0, pos - context_chars // 2)
                end = min(len(content), pos + len(query) + context_chars // 2)
                context = content[start:end]
                matches.append((file_path.stem, context))
            if len(matches) >= limit:
                break
        return matches

    # ------------------------------------------------------------------
    # Formatting Helpers
    # ------------------------------------------------------------------

    def _format_shard(
        self,
        shard_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Format a shard as Markdown."""
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        md = metadata or {}

        meta_lines = []
        if md.get("shard_type"):
            meta_lines.append(f"shard_type: {md['shard_type']}")
        if md.get("source"):
            meta_lines.append(f"source: {md['source']}")
        if md.get("created_at"):
            created_at = md["created_at"]
            # Handle both string (ISO format) and numeric timestamp
            if isinstance(created_at, str):
                created_str = created_at
            else:
                created_str = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(created_at))
            meta_lines.append(f"created_at: {created_str}")
        else:
            meta_lines.append(f"created_at: {now}")
        if md.get("chunk_id"):
            meta_lines.append(f"chunk_id: {md['chunk_id']}")
        if md.get("cluster_id"):
            meta_lines.append(f"cluster_id: {md['cluster_id']}")
        if md:
            meta_lines.append(f"metadata: {md}")

        meta_block = "\n".join(meta_lines)

        return f"""## Shard: {shard_id}

{content}

<!--
{meta_block}
-->"""

    def _format_chunk(
        self,
        chunk_id: str,
        chunk_name: str,
        shards: list[tuple[str, str]],
        description: str = "",
    ) -> str:
        """Format a chunk aggregate as Markdown."""
        lines = [
            f"# Chunk: {chunk_name}",
            f"",
            f"ID: {chunk_id}",
        ]
        if description:
            lines.append(f"Description: {description}")
        lines.append(f"Shard Count: {len(shards)}")
        lines.append(f"---")
        lines.append(f"")

        for shard_id, content in shards:
            lines.append(f"### Shard: {shard_id}")
            lines.append(f"")
            lines.append(content)
            lines.append(f"")
            lines.append(f"---")
            lines.append(f"")

        return "\n".join(lines)

    def _format_cluster(
        self,
        cluster_id: str,
        cluster_name: str,
        chunk_ids: list[str],
        description: str = "",
    ) -> str:
        """Format a cluster index as Markdown."""
        lines = [
            f"# Cluster: {cluster_name}",
            f"",
            f"ID: {cluster_id}",
        ]
        if description:
            lines.append(f"Description: {description}")
        lines.append(f"Chunk Count: {len(chunk_ids)}")
        lines.append(f"---")
        lines.append(f"")
        lines.append(f"## Chunks")
        lines.append(f"")
        for chunk_id in chunk_ids:
            lines.append(f"- [{chunk_id}](../chunks/{chunk_id}.md)")

        return "\n".join(lines)

    def _parse_shard_content(self, file_path: Path) -> str:
        """Extract content from a shard Markdown file."""
        text = file_path.read_text(encoding="utf-8")

        # Find content between header and metadata comment
        lines = text.split("\n")
        content_lines = []
        in_content = False

        for line in lines:
            if line.startswith("## Shard:"):
                in_content = True
                continue
            if line.strip() == "<!--":
                break
            if in_content and not line.startswith("##"):
                content_lines.append(line)

        # Remove trailing empty lines
        while content_lines and content_lines[-1].strip() == "":
            content_lines.pop()

        return "\n".join(content_lines).strip()

    def _extract_metadata(self, text: str) -> dict[str, Any]:
        """Extract metadata from Markdown comment block."""
        import re

        # Find <!-- ... --> block
        match = re.search(r"<!--\s*(.*?)\s*-->", text, re.DOTALL)
        if not match:
            return {}

        meta_text = match.group(1)
        result = {}

        # Parse key: value lines
        for line in meta_text.strip().split("\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip()
                if key == "metadata":
                    # Try to parse dict
                    try:
                        import ast
                        result.update(ast.literal_eval(value))
                    except Exception:
                        pass
                else:
                    result[key] = value

        return result

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def clear_all(self) -> None:
        """Clear all content files (for testing/reset)."""
        for d in [self._shards_dir, self._chunks_dir, self._clusters_dir, self._archive_dir]:
            for f in d.glob("*.md"):
                f.unlink()

    def get_stats(self) -> dict[str, int]:
        """Get store statistics."""
        return {
            "shards": len(list(self._shards_dir.glob("*.md"))),
            "chunks": len(list(self._chunks_dir.glob("*.md"))),
            "clusters": len(list(self._clusters_dir.glob("*.md"))),
            "archived": len(list(self._archive_dir.glob("*.md"))),
        }