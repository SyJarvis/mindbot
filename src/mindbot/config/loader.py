"""Configuration loader — JSON with env-var substitution and multi-source merge."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .env_subst import substitute
from .schema import Config


# ============================================================================
# Deep merge
# ============================================================================

def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *override* into *base* (base is not mutated).

    - dict + dict → recursive merge
    - list + list → *override* replaces *base* (no concatenation)
    - scalar → *override* replaces *base*
    """
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


# ============================================================================
# Config discovery
# ============================================================================

def _discover_config_paths(project_dir: str | Path | None = None) -> list[Path]:
    """Return config files in priority order (lowest → highest).

    Order:
    1. ``~/.mindbot/settings.json`` (global)
    2. ``$MIND_CONFIG_PATH`` (env override)
    3. ``<project>/.mindbot/settings.json`` (project-local)
    """
    paths: list[Path] = []

    # Global config
    global_path = Path.home() / ".mindbot" / "settings.json"
    if global_path.exists():
        paths.append(global_path)

    # Env override
    import os
    env_path = os.environ.get("MIND_CONFIG_PATH")
    if env_path:
        p = Path(env_path).expanduser()
        if p.exists():
            paths.append(p)

    # Project-local config
    if project_dir:
        local_path = Path(project_dir) / ".mindbot" / "settings.json"
        if local_path.exists() and local_path not in paths:
            paths.append(local_path)

    return paths


# ============================================================================
# Public API
# ============================================================================

def load_config(
    path: str | Path | None = None,
    *,
    project_dir: str | Path | None = None,
    missing_env: str = "error",
) -> Config:
    """Load a :class:`Config` from a JSON file, or from env vars only.

    Loading pipeline:
        1. Read JSON file
        2. Substitute ``{env:VAR}`` placeholders
        3. Validate with Pydantic → ``Config``

    When *path* is ``None`` the loader discovers config files automatically via
    :func:`_discover_config_paths` and deep-merges them.

    Args:
        path: Explicit path to a config file. Supports ``~`` expansion.
            Must be a ``.json`` file.
        project_dir: Project directory for auto-discovery (only when *path*
            is ``None``).
        missing_env: How to handle missing env vars: ``"error"``, ``"empty"``,
            or ``"keep"``.
    """
    if path is not None:
        data = _load_single_file(Path(path).expanduser())
    else:
        config_paths = _discover_config_paths(project_dir)
        if not config_paths:
            return Config()
        data: dict[str, Any] = {}
        for cp in config_paths:
            file_data = _load_single_file(cp)
            data = _deep_merge(data, file_data)

    # Substitute env vars
    data = substitute(data, missing=missing_env)

    return Config(**data)


def _load_single_file(p: Path) -> dict[str, Any]:
    """Load a single JSON config file."""
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {p}")

    if p.suffix.lower() != ".json":
        raise ValueError(f"Config file must be JSON (.json): {p}")

    raw = p.read_text(encoding="utf-8")
    return json.loads(raw)
