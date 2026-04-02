"""File watcher for config hot-reload.

Uses ``watchfiles`` (if available) or falls back to polling.
Watches a single config file and calls a callback on changes.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from typing import Callable, Awaitable

logger = logging.getLogger("mindbot.config.watcher")


async def start_watcher(
    path: Path,
    on_change: Callable[[], Awaitable[None]],
    *,
    debounce_ms: int = 200,
) -> None:
    """Watch *path* for changes and call *on_change* when it changes.

    Uses ``watchfiles`` if available, otherwise falls back to a simple
    polling-based watcher (checks every 2 seconds).

    Args:
        path: Config file to watch.
        on_change: Async callback invoked after a confirmed change.
        debounce_ms: Debounce interval in milliseconds.
    """
    try:
        from watchfiles import awatch
        await _watch_with_watchfiles(path, on_change, awatch, debounce_ms)
    except ImportError:
        logger.info("watchfiles not installed — using polling-based watcher")
        await _watch_with_polling(path, on_change)


async def _watch_with_watchfiles(
    path: Path,
    on_change: Callable[[], Awaitable[None]],
    awatch: Any,
    debounce_ms: int,
) -> None:
    """Watch using the ``watchfiles`` library."""
    watch_dir = str(path.parent)
    watch_file = path.name

    async for changes in awatch(watch_dir, stop_event=asyncio.Event()):
        # Check if our target file changed
        for change_type, changed_path in changes:
            if Path(changed_path).name == watch_file:
                logger.debug("Config file changed: %s", changed_path)
                # Debounce: small delay to let writes complete
                await asyncio.sleep(debounce_ms / 1000)
                await on_change()
                break


async def _watch_with_polling(
    path: Path,
    on_change: Callable[[], Awaitable[None]],
    *,
    poll_interval: float = 2.0,
) -> None:
    """Fallback polling-based watcher (checks hash every *poll_interval* seconds)."""
    last_hash = _file_hash(path)

    while True:
        await asyncio.sleep(poll_interval)
        try:
            current_hash = _file_hash(path)
            if current_hash != last_hash:
                logger.debug("Config file changed (polling detected)")
                last_hash = current_hash
                await on_change()
        except FileNotFoundError:
            logger.warning("Config file disappeared: %s", path)
        except Exception:
            logger.exception("Error polling config file")


def _file_hash(path: Path) -> str:
    """Compute a quick MD5 hash of a file."""
    content = path.read_bytes()
    return hashlib.md5(content).hexdigest()
