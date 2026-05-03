"""Centralised logging setup for MindBot.

All modules inside ``src/mindbot`` should import ``logger`` from here::

    from mindbot.logging import logger
    from mindbot.logging import set_log_context

Do NOT import directly from loguru or stdlib logging in mindbot code.
The stdlib logging bridge ensures that third-party libraries whose logs flow
through stdlib ``logging`` are also routed through loguru sinks.
"""

from __future__ import annotations

import logging
import os
import sys
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import BaseModel

__all__ = ["logger", "LoggingConfig", "setup_logging", "set_log_context"]


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class LoggingConfig(BaseModel):
    """Logging configuration knobs for MindBot.

    File layout under ``~/.mindbot/logs/``::

        mindbot.log          ← same ``level`` threshold as stderr
        mindbot_YYYY-MM-DD_HH-mm-ss.log.zip  ← compressed daily archives
        error.log            ← WARNING and above only (for quick triage)
        error_YYYY-MM-DD_HH-mm-ss.log.zip

    ``level`` applies to both stderr and ``mindbot.log``.  For turn/chat
    tracing, set ``level`` to ``INFO`` or ``DEBUG`` in config, or export
    ``MINDBOT_LOG_LEVEL``.
    """

    level: str = "WARNING"
    file: bool = True
    rotation: str = "00:00"      # rotate at midnight every day
    retention: str = "30 days"   # keep 30 days of archives
    compression: str = "zip"     # compress rotated files


# ---------------------------------------------------------------------------
# Per-async-task context variables
# ---------------------------------------------------------------------------

_session_id_var: ContextVar[str] = ContextVar("mindbot_session_id", default="")
_turn_id_var: ContextVar[str] = ContextVar("mindbot_turn_id", default="")


def set_log_context(session_id: str | None = None, turn_id: str | None = None) -> None:
    """Set the session / turn context for the current async task.

    Only the arguments explicitly passed (not None) are updated, so callers
    can set just one field without clearing the other::

        set_log_context(session_id="abc")   # turn_id unchanged
        set_log_context(turn_id="xyz")      # session_id unchanged
        set_log_context(session_id="", turn_id="")  # clear both
    """
    if session_id is not None:
        _session_id_var.set(session_id)
    if turn_id is not None:
        _turn_id_var.set(turn_id)


def _patch_context(record: dict[str, Any]) -> None:
    """Inject session_id / turn_id from ContextVars into every log record."""
    record["extra"]["sid"] = _session_id_var.get()
    record["extra"]["tid"] = _turn_id_var.get()


# ---------------------------------------------------------------------------
# Stdlib → loguru bridge (for third-party libraries only)
# ---------------------------------------------------------------------------


class _PropagateHandler(logging.Handler):
    """Route stdlib logging records into the loguru pipeline."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame, depth = frame.f_back, depth + 1  # type: ignore[assignment]
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


# ---------------------------------------------------------------------------
# Log formats
# ---------------------------------------------------------------------------

_STDERR_FORMAT = (
    "<green>{time:HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{line}</cyan>"
    "[<dim>{extra[sid]}</dim>/<dim>{extra[tid]}</dim>] "
    "- {message}"
)

_FILE_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
    "{name}:{function}:{line} | {extra[sid]}/{extra[tid]} - {message}"
)


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


def setup_logging(config: LoggingConfig | None = None) -> None:
    """Initialise loguru sinks and the stdlib bridge.

    Should be called **once** during application startup (``MindBot.__init__``).
    Subsequent calls are idempotent (all sinks are removed and re-added).

    Effective ``level`` for **stderr** and **mindbot.log** (highest priority first):

      1. ``MINDBOT_LOG_LEVEL`` environment variable
      2. ``config.level`` field
      3. Default ``"WARNING"``
    """
    cfg = config or LoggingConfig()
    level = os.environ.get("MINDBOT_LOG_LEVEL", cfg.level).upper()

    # Reset all existing handlers
    logger.remove()

    # Install context patcher and provide default extra fields
    logger.configure(extra={"sid": "", "tid": ""}, patcher=_patch_context)

    # stderr sink — colorised, for interactive use
    logger.add(
        sys.stderr,
        level=level,
        format=_STDERR_FORMAT,
        colorize=True,
    )

    # File sinks
    if cfg.file:
        log_dir = Path.home() / ".mindbot" / "logs"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            # Main log — same threshold as stderr
            logger.add(
                log_dir / "mindbot.log",
                level=level,
                format=_FILE_FORMAT,
                rotation=cfg.rotation,
                retention=cfg.retention,
                compression=cfg.compression,
                encoding="utf-8",
            )
            # Error log — WARNING and above only, for quick triage
            logger.add(
                log_dir / "error.log",
                level="WARNING",
                format=_FILE_FORMAT,
                rotation=cfg.rotation,
                retention=cfg.retention,
                compression=cfg.compression,
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Could not create log file sinks: {}", exc)

    # Bridge: root stdlib logger → loguru
    # This catches third-party libraries (e.g. aiohttp, matrix-nio) that still
    # use stdlib logging.  We do NOT propagate mindbot's own records through
    # this path because mindbot code uses loguru directly.
    root = logging.getLogger()
    for h in list(root.handlers):
        if isinstance(h, _PropagateHandler):
            root.removeHandler(h)
    root.addHandler(_PropagateHandler())
    root.setLevel(logging.DEBUG)  # Let loguru sinks handle level filtering
