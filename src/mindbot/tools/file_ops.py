"""Built-in file operation tools."""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any

from mindbot.capability.backends.tooling.models import Tool


def _resolve_path(path: str, workspace: Path, allowed_dir: Path | None) -> Path:
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = workspace / target
    resolved = target.resolve()
    if allowed_dir is not None:
        resolved.relative_to(allowed_dir.resolve())
    return resolved


def _line_slice(content: str, offset: int = 0, limit: int | None = None) -> str:
    lines = content.splitlines()
    start = max(offset, 0)
    end = start + limit if limit is not None else len(lines)
    selected = lines[start:end]
    if not selected:
        return ""
    numbered = [f"{index}|{line}" for index, line in enumerate(selected, start=start + 1)]
    return "\n".join(numbered)


def create_file_tools(
    workspace: Path | None = None,
    *,
    restrict_to_workspace: bool = True,
) -> list[Tool]:
    """Create the built-in file tools bound to *workspace*."""
    root = (workspace or Path.cwd()).expanduser().resolve()
    allowed_dir = root if restrict_to_workspace else None

    def read_file(
        path: str,
        encoding: str = "utf-8",
        offset: int = 0,
        limit: int | None = None,
    ) -> str:
        try:
            file_path = _resolve_path(path, root, allowed_dir)
        except ValueError:
            return f"Error: path is outside the allowed workspace: {path}"

        if not file_path.exists():
            return f"Error: file not found: {path}"
        if not file_path.is_file():
            return f"Error: not a file: {path}"

        content = file_path.read_text(encoding=encoding)
        return _line_slice(content, offset=offset, limit=limit)

    def write_file(
        path: str,
        content: str,
        encoding: str = "utf-8",
        create_dirs: bool = True,
    ) -> str:
        try:
            file_path = _resolve_path(path, root, allowed_dir)
        except ValueError:
            return f"Error: path is outside the allowed workspace: {path}"

        if create_dirs:
            file_path.parent.mkdir(parents=True, exist_ok=True)

        file_path.write_text(content, encoding=encoding)
        return f"Successfully wrote {len(content)} characters to {file_path}"

    def edit_file(
        path: str,
        old_string: str,
        new_string: str,
        encoding: str = "utf-8",
        replace_all: bool = False,
    ) -> str:
        try:
            file_path = _resolve_path(path, root, allowed_dir)
        except ValueError:
            return f"Error: path is outside the allowed workspace: {path}"

        if not file_path.exists():
            return f"Error: file not found: {path}"
        if not file_path.is_file():
            return f"Error: not a file: {path}"
        if not old_string:
            return "Error: old_string must not be empty"
        if old_string == new_string:
            return "Error: old_string and new_string are identical"

        content = file_path.read_text(encoding=encoding)
        count = content.count(old_string)
        if count == 0:
            return f"Error: old_string not found in {path}"
        if count > 1 and not replace_all:
            return (
                f"Error: old_string appears {count} times in {path}. "
                "Provide more context or set replace_all=true."
            )

        updated = (
            content.replace(old_string, new_string)
            if replace_all
            else content.replace(old_string, new_string, 1)
        )
        file_path.write_text(updated, encoding=encoding)
        replaced = count if replace_all else 1
        return f"Replaced {replaced} occurrence(s) in {file_path}"

    def list_directory(
        path: str = ".",
        pattern: str = "*",
        include_hidden: bool = False,
    ) -> str:
        try:
            dir_path = _resolve_path(path, root, allowed_dir)
        except ValueError:
            return f"Error: path is outside the allowed workspace: {path}"

        if not dir_path.exists():
            return f"Error: directory not found: {path}"
        if not dir_path.is_dir():
            return f"Error: not a directory: {path}"

        items: list[str] = []
        for entry in sorted(dir_path.iterdir(), key=lambda item: item.name.lower()):
            if not include_hidden and entry.name.startswith("."):
                continue
            if not fnmatch.fnmatch(entry.name, pattern):
                continue
            prefix = "[DIR]" if entry.is_dir() else "[FILE]"
            items.append(f"{prefix} {entry.name}")
        if not items:
            return f"No entries found matching pattern '{pattern}'"
        return "\n".join(items)

    def file_info(path: str) -> str:
        try:
            target = _resolve_path(path, root, allowed_dir)
        except ValueError:
            return f"Error: path is outside the allowed workspace: {path}"

        if not target.exists():
            return f"[NOT FOUND] {path}"
        if target.is_dir():
            try:
                count = sum(1 for _ in target.iterdir())
            except OSError:
                return f"[DIR] {target} (permission denied)"
            return f"[DIR] {target} ({count} items)"
        if target.is_file():
            return f"[FILE] {target} ({target.stat().st_size} bytes)"
        return f"[OTHER] {target}"

    return [
        Tool(
            name="read_file",
            description="Read a file from the workspace. Supports optional offset and limit for partial reads.",
            parameters_schema_override={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to read."},
                    "encoding": {"type": "string", "description": "Text encoding.", "default": "utf-8"},
                    "offset": {"type": "integer", "description": "Start line offset (0-based).", "default": 0},
                    "limit": {"type": "integer", "description": "Maximum number of lines to read."},
                },
                "required": ["path"],
            },
            handler=read_file,
        ),
        Tool(
            name="write_file",
            description="Write content to a file. Creates parent directories when requested.",
            parameters_schema_override={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to write."},
                    "content": {"type": "string", "description": "Full file content."},
                    "encoding": {"type": "string", "description": "Text encoding.", "default": "utf-8"},
                    "create_dirs": {
                        "type": "boolean",
                        "description": "Create parent directories when missing.",
                        "default": True,
                    },
                },
                "required": ["path", "content"],
            },
            handler=write_file,
        ),
        Tool(
            name="edit_file",
            description="Replace exact text in a file. Requires unique old_string unless replace_all is true.",
            parameters_schema_override={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to edit."},
                    "old_string": {"type": "string", "description": "Exact text to replace."},
                    "new_string": {"type": "string", "description": "Replacement text."},
                    "encoding": {"type": "string", "description": "Text encoding.", "default": "utf-8"},
                    "replace_all": {
                        "type": "boolean",
                        "description": "Replace all matches instead of one unique match.",
                        "default": False,
                    },
                },
                "required": ["path", "old_string", "new_string"],
            },
            handler=edit_file,
        ),
        Tool(
            name="list_directory",
            description="List files and directories under a workspace path.",
            parameters_schema_override={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path.", "default": "."},
                    "pattern": {"type": "string", "description": "Glob-like name pattern.", "default": "*"},
                    "include_hidden": {
                        "type": "boolean",
                        "description": "Include dotfiles and dot-directories.",
                        "default": False,
                    },
                },
            },
            handler=list_directory,
        ),
        Tool(
            name="file_info",
            description="Return basic information about a workspace file or directory.",
            parameters_schema_override={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Target file or directory path."},
                },
                "required": ["path"],
            },
            handler=file_info,
        ),
    ]
