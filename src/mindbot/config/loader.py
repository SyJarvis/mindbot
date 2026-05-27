"""Configuration loader — JSON with env-var substitution and multi-source merge."""

from __future__ import annotations

import json
import os
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
# Convenience env vars
# ============================================================================

def _has_convenience_env_vars() -> bool:
    """Return True if any MINDBOT_* convenience env var is set."""
    return bool(
        os.environ.get("MINDBOT_MODEL")
        or os.environ.get("MINDBOT_MODELS")
        or os.environ.get("MINDBOT_BASE_URL")
        or os.environ.get("MINDBOT_PLATFORM")
    )


def _apply_convenience_env_vars(data: dict[str, Any]) -> dict[str, Any]:
    """Apply MINDBOT_* convenience env vars as overrides.

    These are simple env vars for quick configuration without needing
    a full settings.json or complex MIND_* nested vars:

    * ``MINDBOT_MODEL`` / ``MINDBOT_MODELS`` → ``agent.model``
    * ``MINDBOT_API_KEY`` → provider endpoint ``api_key``
    * ``MINDBOT_BASE_URL`` → provider endpoint ``base_url``
    * ``MINDBOT_PLATFORM`` → provider instance name (dict key in ``providers``)
    * ``MINDBOT_PROVIDER`` → provider ``type`` (e.g. ``"openai"``)
    """
    _model = os.environ.get("MINDBOT_MODELS") or os.environ.get("MINDBOT_MODEL")
    _api_key = os.environ.get("MINDBOT_API_KEY")
    _base_url = os.environ.get("MINDBOT_BASE_URL")
    _platform = os.environ.get("MINDBOT_PLATFORM")
    _provider_type = os.environ.get("MINDBOT_PROVIDER")

    if _model:
        data.setdefault("agent", {})["model"] = _model

    if _base_url:
        _ensure_provider(data, _base_url, _api_key, _platform, _provider_type)
    elif _platform:
        _rename_provider_key(data, _platform)

    if _provider_type and not _base_url:
        for prov in data.get("providers", {}).values():
            prov["type"] = _provider_type

    return data


def _ensure_provider(
    data: dict[str, Any],
    base_url: str,
    api_key: str | None,
    platform: str | None,
    provider_type: str | None,
) -> None:
    """Ensure a provider entry exists with the given *base_url* and *api_key*.

    If *platform* is given, it is used as the provider key.  Otherwise the
    first existing provider key is kept, or ``"default"`` is used.
    """
    providers = data.setdefault("providers", {})
    ptype = provider_type or "openai"

    if platform:
        # Rename or create the provider key
        if providers and platform not in providers:
            old_key = next(iter(providers))
            providers[platform] = providers.pop(old_key)
        if platform not in providers:
            providers[platform] = {"type": ptype, "endpoints": []}
        target = providers[platform]
    elif providers:
        target = next(iter(providers.values()))
    else:
        providers["default"] = {"type": ptype, "endpoints": []}
        target = providers["default"]

    target["type"] = ptype
    endpoints = target.setdefault("endpoints", [])
    if endpoints:
        endpoints[0]["base_url"] = base_url
        if api_key:
            endpoints[0]["api_key"] = api_key
    else:
        endpoints.append({"base_url": base_url, "api_key": api_key or "", "models": []})

    # Ensure agent.model has the platform prefix
    _prefix_model(data, platform or next(iter(providers), "default"))


def _rename_provider_key(data: dict[str, Any], platform: str) -> None:
    """Rename the first provider key to *platform* and update agent.model."""
    providers = data.get("providers", {})
    if not providers:
        return
    old_key = next(iter(providers))
    if old_key == platform:
        return
    providers[platform] = providers.pop(old_key)
    _prefix_model(data, platform)


def _prefix_model(data: dict[str, Any], platform: str) -> None:
    """Prefix ``agent.model`` with *platform* if it lacks a prefix."""
    agent_model = data.get("agent", {}).get("model", "")
    if not agent_model:
        return
    if "/" not in agent_model:
        data["agent"]["model"] = f"{platform}/{agent_model}"


# ============================================================================
# Public API
# ============================================================================

def load_config(
    path: str | Path | None = None,
    *,
    project_dir: str | Path | None = None,
    missing_env: str = "empty",
) -> Config:
    """Load a :class:`Config` from a JSON file, or from env vars only.

    Loading pipeline:
        1. Read JSON file(s)
        2. Substitute ``{env:VAR}`` placeholders
        3. Apply ``MINDBOT_*`` convenience env vars
        4. Validate with Pydantic → ``Config`` (``MIND_*`` env vars applied)

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
            if _has_convenience_env_vars():
                data = {}
            else:
                return Config()
        else:
            data: dict[str, Any] = {}
            for cp in config_paths:
                file_data = _load_single_file(cp)
                data = _deep_merge(data, file_data)

    # Substitute env vars
    data = substitute(data, missing=missing_env)

    # Apply convenience MINDBOT_* env vars
    data = _apply_convenience_env_vars(data)

    return Config(**data)


def _load_single_file(p: Path) -> dict[str, Any]:
    """Load a single JSON config file."""
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {p}")

    if p.suffix.lower() != ".json":
        raise ValueError(f"Config file must be JSON (.json): {p}")

    raw = p.read_text(encoding="utf-8")
    return json.loads(raw)
