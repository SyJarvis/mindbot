"""Markdown file storage for human-readable memory shards."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


class MarkdownStorage:
    """Store short/long-term memory in markdown files."""

    def __init__(self, base_path: str = "~/.Mindbot/data/memory") -> None:
        self.base_path = Path(base_path).expanduser()
        self.short_term_path = self.base_path / "short_term"
        self.long_term_path = self.base_path / "long_term"
        self.short_term_path.mkdir(parents=True, exist_ok=True)
        self.long_term_path.mkdir(parents=True, exist_ok=True)

    def write_short_term(
        self,
        date: str,
        content: str,
        *,
        mode: str = "a",
        metadata: dict[str, Any] | None = None,
    ) -> Path:
        file_path = self.short_term_path / f"{date}.md"
        if mode not in {"a", "w"}:
            raise ValueError("mode must be 'a' or 'w'")
        payload = self._format_entry(content, metadata)
        with file_path.open(mode, encoding="utf-8") as f:
            f.write(payload)
        return file_path

    def read_short_term(self, date: str) -> str:
        file_path = self.short_term_path / f"{date}.md"
        if not file_path.exists():
            return ""
        return file_path.read_text(encoding="utf-8")

    def list_short_term_dates(self, days: int = 30) -> list[str]:
        cutoff = datetime.now() - timedelta(days=days)
        dates: list[str] = []
        for file in sorted(self.short_term_path.glob("*.md")):
            try:
                dt = datetime.strptime(file.stem, "%Y-%m-%d")
            except ValueError:
                continue
            if dt >= cutoff:
                dates.append(file.stem)
        return sorted(dates, reverse=True)

    def write_long_term(
        self,
        filename: str,
        content: str,
        *,
        mode: str = "a",
        metadata: dict[str, Any] | None = None,
    ) -> Path:
        safe_filename = filename if filename.endswith(".md") else f"{filename}.md"
        file_path = self.long_term_path / safe_filename
        if mode not in {"a", "w"}:
            raise ValueError("mode must be 'a' or 'w'")
        payload = self._format_entry(content, metadata)
        with file_path.open(mode, encoding="utf-8") as f:
            f.write(payload)
        return file_path

    def read_long_term(self, filename: str = "MEMORY.md") -> str:
        safe_filename = filename if filename.endswith(".md") else f"{filename}.md"
        file_path = self.long_term_path / safe_filename
        if not file_path.exists():
            return ""
        return file_path.read_text(encoding="utf-8")

    def list_long_term(self) -> list[str]:
        return sorted(f.name for f in self.long_term_path.glob("*.md"))

    def delete_short_term_before(self, cutoff_date: str) -> int:
        cutoff = datetime.strptime(cutoff_date, "%Y-%m-%d")
        deleted = 0
        for file in self.short_term_path.glob("*.md"):
            try:
                dt = datetime.strptime(file.stem, "%Y-%m-%d")
            except ValueError:
                continue
            if dt < cutoff:
                file.unlink(missing_ok=True)
                deleted += 1
        return deleted

    @staticmethod
    def _format_entry(content: str, metadata: dict[str, Any] | None = None) -> str:
        now = datetime.now().isoformat(timespec="seconds")
        md = metadata or {}
        location = str(md.get("location", "unknown"))
        meta_bits = [f"time={now}", f"location={location}"]
        return f"### {now}\n\n{content}\n\n<!-- {'; '.join(meta_bits)} -->\n\n"
