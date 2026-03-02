"""JSONL-based append-only session journal store."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from mindbot.session.types import SessionMessage
from mindbot.utils import get_logger

logger = get_logger("session.store")


class SessionJournal:
    """Append-only JSONL store keyed by *session_id*.

    Directory layout::

        <base_path>/
            <session_id>.jsonl   # one JSON object per line

    Each line is a :class:`SessionMessage` serialised via
    :meth:`SessionMessage.to_dict`.
    """

    def __init__(self, base_path: str | Path) -> None:
        self._base = Path(base_path).expanduser()
        self._base.mkdir(parents=True, exist_ok=True)

    def _session_path(self, session_id: str) -> Path:
        safe_name = session_id.replace("/", "_").replace("\\", "_")
        return self._base / f"{safe_name}.jsonl"

    def append(self, session_id: str, messages: Sequence[SessionMessage]) -> None:
        """Append *messages* to the journal for *session_id*."""
        if not messages:
            return
        path = self._session_path(session_id)
        with path.open("a", encoding="utf-8") as fh:
            for msg in messages:
                fh.write(json.dumps(msg.to_dict(), ensure_ascii=False))
                fh.write("\n")
        logger.debug(
            "Appended %d message(s) to session journal %s", len(messages), session_id
        )

    def read(self, session_id: str) -> list[SessionMessage]:
        """Read the full timeline for *session_id*.

        Returns an empty list when the session file does not exist.
        """
        path = self._session_path(session_id)
        if not path.exists():
            return []
        entries: list[SessionMessage] = []
        with path.open(encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(SessionMessage.from_dict(json.loads(line)))
                except Exception:
                    logger.warning(
                        "Skipping malformed line %d in %s", lineno, path
                    )
        return entries

    def list_sessions(self) -> list[str]:
        """Return all session IDs that have journal files."""
        return sorted(
            p.stem for p in self._base.glob("*.jsonl")
        )

    def session_exists(self, session_id: str) -> bool:
        return self._session_path(session_id).exists()
