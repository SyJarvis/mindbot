"""ToolDefinition registry – persistent storage at ``~/.mindbot/tools/``.

Each :class:`~mindbot.generation.models.ToolDefinition` is stored as a
single JSON file: ``<store_dir>/<name>.json``.  The name is used as the
filename so that collisions are visible in the filesystem.

Environment variable ``MINDBOT_TOOLS_DIR`` overrides the default directory,
which is useful during tests.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Iterator

from mindbot.generation.models import (
    ToolDefinition,
    ToolDefinitionConflictError,
    ToolDefinitionError,
    ToolDefinitionNotFoundError,
)
from mindbot.generation.validator import validate_tool_definition
from mindbot.utils import get_logger

logger = get_logger("generation.registry")

_DEFAULT_DIR = Path.home() / ".mindbot" / "tools"
_ENV_KEY = "MINDBOT_TOOLS_DIR"


def _store_dir() -> Path:
    """Return the storage directory, honouring the env-var override."""
    override = os.environ.get(_ENV_KEY)
    return Path(override) if override else _DEFAULT_DIR


class ToolDefinitionRegistry:
    """Persistent registry of :class:`~mindbot.generation.models.ToolDefinition`.

    All mutations (save/update/delete) are immediately written to disk so
    that definitions survive process restarts.

    Usage::

        registry = ToolDefinitionRegistry()
        registry.save(my_definition)
        registry.load_all()
        defn = registry.get_by_id("some-uuid")
    """

    def __init__(self, store_dir: Path | None = None) -> None:
        self._dir: Path = store_dir or _store_dir()
        self._by_id: dict[str, ToolDefinition] = {}
        self._by_name: dict[str, str] = {}  # name -> id

    # ------------------------------------------------------------------
    # Startup loading
    # ------------------------------------------------------------------

    def load_all(self) -> int:
        """Load all definition files from the store directory.

        Returns:
            Number of definitions successfully loaded.
        """
        self._dir.mkdir(parents=True, exist_ok=True)
        loaded = 0
        for path in sorted(self._dir.glob("*.json")):
            try:
                self._load_file(path)
                loaded += 1
            except Exception as exc:
                logger.warning("Failed to load tool definition from %s: %s", path, exc)
        logger.info("Loaded %d tool definitions from %s", loaded, self._dir)
        return loaded

    def _load_file(self, path: Path) -> ToolDefinition:
        data = json.loads(path.read_text(encoding="utf-8"))
        defn = ToolDefinition.from_dict(data)
        validate_tool_definition(defn)
        # Re-register in memory (load_all clears first)
        self._by_id[defn.id] = defn
        self._by_name[defn.name] = defn.id
        return defn

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def save(self, defn: ToolDefinition, *, replace: bool = False) -> None:
        """Persist a new definition.

        Args:
            defn: The definition to save.
            replace: When *True*, an existing definition with the same *name*
                is silently overwritten.  When *False* (default) a
                :exc:`~mindbot.generation.models.ToolDefinitionConflictError`
                is raised.

        Raises:
            ToolDefinitionError: When validation fails.
            ToolDefinitionConflictError: When *replace* is *False* and the
                name already exists.
        """
        validate_tool_definition(defn)

        existing_id = self._by_name.get(defn.name)
        if existing_id and not replace:
            raise ToolDefinitionConflictError(defn.name)

        # Remove the old file if we are replacing a different ID
        if existing_id and existing_id != defn.id:
            old_defn = self._by_id.get(existing_id)
            if old_defn:
                self._delete_file(old_defn)
            del self._by_id[existing_id]

        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._file_path(defn)
        path.write_text(
            json.dumps(defn.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self._by_id[defn.id] = defn
        self._by_name[defn.name] = defn.id
        logger.debug("Saved tool definition '%s' -> %s", defn.name, path)

    def update(self, defn: ToolDefinition) -> None:
        """Update an existing definition (by ID).

        The definition must already exist.  Its ``updated_at`` timestamp is
        refreshed automatically.

        Args:
            defn: The updated definition.  ``defn.id`` must match an existing
                entry.

        Raises:
            ToolDefinitionNotFoundError: When the ID is not known.
            ToolDefinitionError: When validation fails.
        """
        if defn.id not in self._by_id:
            raise ToolDefinitionNotFoundError(defn.id)

        validate_tool_definition(defn)
        defn.updated_at = time.time()

        # Handle name change: remove old file + name mapping
        old_defn = self._by_id[defn.id]
        if old_defn.name != defn.name:
            self._delete_file(old_defn)
            del self._by_name[old_defn.name]

        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._file_path(defn)
        path.write_text(
            json.dumps(defn.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self._by_id[defn.id] = defn
        self._by_name[defn.name] = defn.id
        logger.debug("Updated tool definition '%s'", defn.name)

    def delete(self, definition_id: str) -> None:
        """Remove a definition by ID.

        Args:
            definition_id: The ID of the definition to remove.

        Raises:
            ToolDefinitionNotFoundError: When the ID is not known.
        """
        defn = self._by_id.get(definition_id)
        if defn is None:
            raise ToolDefinitionNotFoundError(definition_id)

        self._delete_file(defn)
        del self._by_id[defn.id]
        del self._by_name[defn.name]
        logger.debug("Deleted tool definition '%s'", defn.name)

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_by_id(self, definition_id: str) -> ToolDefinition | None:
        """Return the definition with the given ID, or *None*."""
        return self._by_id.get(definition_id)

    def get_by_name(self, name: str) -> ToolDefinition | None:
        """Return the definition with the given name, or *None*."""
        did = self._by_name.get(name)
        return self._by_id.get(did) if did else None

    def list_all(self) -> list[ToolDefinition]:
        """Return all loaded definitions."""
        return list(self._by_id.values())

    def __iter__(self) -> Iterator[ToolDefinition]:
        return iter(self._by_id.values())

    def __len__(self) -> int:
        return len(self._by_id)

    def __contains__(self, definition_id: str) -> bool:
        return definition_id in self._by_id

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _file_path(self, defn: ToolDefinition) -> Path:
        safe_name = defn.name.replace("/", "_").replace("\\", "_")
        return self._dir / f"{safe_name}.json"

    def _delete_file(self, defn: ToolDefinition) -> None:
        path = self._file_path(defn)
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Could not delete file %s: %s", path, exc)
