"""Minimal configuration loader — file + env, nothing more."""

from __future__ import annotations

from pathlib import Path

from .schema import Config


def load_config(path: str | Path | None = None) -> Config:
    """Load a :class:`Config` from a YAML/JSON file, or from env vars only.

    Args:
        path: Path to a ``.yaml`` / ``.yml`` / ``.json`` config file.
              Supports ``~`` expansion for home directory.
              If *None*, returns defaults merged with environment variables.
    """
    if path is None:
        return Config()

    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {p}")

    ext = p.suffix.lower()
    if ext in (".yaml", ".yml"):
        import yaml

        with open(p) as f:
            data = yaml.safe_load(f) or {}
    elif ext == ".json":
        import json

        with open(p) as f:
            data = json.load(f)
    else:
        raise ValueError(f"Unsupported config format: {ext}")

    return Config(**data)
