"""Environment variable substitution for config values.

Replaces ``{env:VAR_NAME}`` placeholders in all string values of a config dict.
"""

from __future__ import annotations

import os
import re
from typing import Any

# Matches {env:VAR_NAME} — VAR_NAME must be a valid env var identifier
_ENV_PATTERN = re.compile(r"\{env:([A-Za-z_][A-Za-z0-9_]*)\}")


class EnvSubstError(Exception):
    """Raised when an env var referenced in config is not set."""


def substitute(
    data: Any,
    *,
    missing: str = "error",
) -> Any:
    """Recursively substitute ``{env:VAR}`` in all string values.

    Args:
        data: Parsed config data (dict / list / scalar).
        missing: How to handle missing env vars.
            - ``"error"``: raise :class:`EnvSubstError`.
            - ``"empty"``: replace with empty string.
            - ``"keep"``: leave the placeholder as-is.
    """
    return _walk(data, missing)


def _walk(value: Any, missing: str) -> Any:
    if isinstance(value, str):
        return _substitute_string(value, missing)
    if isinstance(value, dict):
        return {_walk(k, missing): _walk(v, missing) for k, v in value.items()}
    if isinstance(value, list):
        return [_walk(v, missing) for v in value]
    return value


def _substitute_string(text: str, missing: str) -> str:
    def _replacer(m: re.Match) -> str:
        var_name = m.group(1)
        val = os.environ.get(var_name)
        if val is not None:
            return val
        if missing == "empty":
            return ""
        if missing == "keep":
            return m.group(0)
        raise EnvSubstError(
            f"Environment variable {var_name!r} is not set, "
            f"referenced in config as {m.group(0)!r}"
        )

    return _ENV_PATTERN.sub(_replacer, text)
