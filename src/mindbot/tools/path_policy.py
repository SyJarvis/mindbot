"""Shared path policy helpers for workspace-bound tools."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path


def resolve_workspace(workspace: Path | str) -> Path:
    """Resolve the configured workspace path."""
    return Path(workspace).expanduser().resolve()


def resolve_allowed_roots(
    workspace: Path | str,
    *,
    restrict_to_workspace: bool = True,
    allowed_paths: Sequence[Path | str] | None = None,
) -> tuple[Path, list[Path]]:
    """Resolve workspace and allowed path roots for tool access checks."""
    root = resolve_workspace(workspace)
    if not restrict_to_workspace:
        return root, []

    resolved: list[Path] = [root]
    for path in allowed_paths or []:
        candidate = Path(path).expanduser().resolve()
        if candidate not in resolved:
            resolved.append(candidate)
    return root, resolved


def is_within_allowed_roots(path: Path, allowed_roots: Sequence[Path]) -> bool:
    """Return whether *path* is contained by any allowed root."""
    if not allowed_roots:
        return True

    for root in allowed_roots:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def allowed_roots_error(path: str, allowed_roots: Sequence[Path]) -> str:
    """Build a consistent policy error for rejected paths."""
    allowed_text = ", ".join(str(root) for root in allowed_roots) if allowed_roots else "(unrestricted)"
    return f"Error: path is outside the allowed paths: {path} (allowed: {allowed_text})"
