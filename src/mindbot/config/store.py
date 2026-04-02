"""ConfigStore – thread-safe config holder with hot-reload support."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from src.mindbot.config.schema import Config, ProviderInstanceConfig
from src.mindbot.config.loader import load_config

if TYPE_CHECKING:
    pass

logger = logging.getLogger("mindbot.config.store")


class ConfigStore:
    """Thread-safe config holder with file-watcher-based hot-reload.

    Usage::

        store = ConfigStore(config, path=Path("~/.mindbot/settings.json"))
        await store.watch()  # start file watcher

        # Read current config at any time
        cfg = store.config

        # Programmatic provider update
        await store.update_provider("new-openai", ProviderInstanceConfig(...))

        # Register callback for config changes
        store.on_change(my_callback)
    """

    def __init__(
        self,
        config: Config,
        path: Path | None = None,
    ) -> None:
        self._config = config
        self._path = path
        self._lock = asyncio.Lock()
        self._watcher_task: asyncio.Task | None = None
        self._callbacks: list[Callable[[Config], Awaitable[None]]] = []

    @property
    def config(self) -> Config:
        """Current config snapshot."""
        return self._config

    @property
    def path(self) -> Path | None:
        """Config file path (may be None if config was created programmatically)."""
        return self._path

    # ------------------------------------------------------------------
    # Reload
    # ------------------------------------------------------------------

    async def reload(self) -> Config:
        """Reload config from file, validate, and swap atomically.

        Returns:
            The new Config.

        Raises:
            RuntimeError: If no file path is set.
            FileNotFoundError: If the config file is gone.
        """
        if self._path is None:
            raise RuntimeError("Cannot reload: no file path set")

        new_config = load_config(self._path)
        async with self._lock:
            old_config = self._config
            self._config = new_config

        logger.info("Config reloaded from %s", self._path)

        # Notify callbacks outside the lock
        await self._notify_callbacks(new_config, old_config)
        return new_config

    # ------------------------------------------------------------------
    # File watcher
    # ------------------------------------------------------------------

    async def watch(self) -> None:
        """Start watching the config file for changes."""
        if self._path is None:
            logger.warning("Cannot watch: no file path set")
            return

        from src.mindbot.config.watcher import start_watcher
        self._watcher_task = asyncio.create_task(
            start_watcher(self._path, self._on_file_changed)
        )
        logger.info("Watching config file: %s", self._path)

    async def stop_watch(self) -> None:
        """Stop the file watcher."""
        if self._watcher_task is not None:
            self._watcher_task.cancel()
            try:
                await self._watcher_task
            except asyncio.CancelledError:
                pass
            self._watcher_task = None
            logger.info("Stopped watching config file")

    async def _on_file_changed(self) -> None:
        """Called by watcher when the config file changes."""
        try:
            await self.reload()
        except Exception:
            logger.exception("Failed to reload config after file change")

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def on_change(self, callback: Callable[[Config], Awaitable[None]]) -> None:
        """Register a callback invoked when config changes.

        The callback receives the new Config as argument.
        """
        self._callbacks.append(callback)

    def remove_on_change(self, callback: Callable[[Config], Awaitable[None]]) -> None:
        """Remove a previously registered callback."""
        self._callbacks = [cb for cb in self._callbacks if cb is not callback]

    async def _notify_callbacks(self, new_config: Config, old_config: Config) -> None:
        """Invoke all registered callbacks."""
        for callback in self._callbacks:
            try:
                await callback(new_config)
            except Exception:
                logger.exception("Config change callback failed")

    # ------------------------------------------------------------------
    # Programmatic provider management
    # ------------------------------------------------------------------

    async def update_provider(
        self, name: str, provider_config: ProviderInstanceConfig
    ) -> None:
        """Add or update a single provider instance at runtime.

        Args:
            name: Provider instance name.
            provider_config: Full provider configuration.
        """
        async with self._lock:
            old_config = self._config
            # Create a new Config with the updated provider
            providers = dict(self._config.providers)
            providers[name] = provider_config
            self._config = self._config.model_copy(update={"providers": providers})

        logger.info("Provider %s updated", name)
        await self._notify_callbacks(self._config, old_config)

    async def remove_provider(self, name: str) -> bool:
        """Remove a provider instance at runtime.

        Args:
            name: Provider instance name.

        Returns:
            True if the provider was found and removed, False otherwise.
        """
        async with self._lock:
            if name not in self._config.providers:
                return False

            old_config = self._config
            providers = dict(self._config.providers)
            del providers[name]
            self._config = self._config.model_copy(update={"providers": providers})

        logger.info("Provider %s removed", name)
        await self._notify_callbacks(self._config, old_config)
        return True

    async def write_back(self) -> None:
        """Write current in-memory config back to the file.

        Useful after programmatic provider add/remove.

        Raises:
            RuntimeError: If no file path is set.
        """
        if self._path is None:
            raise RuntimeError("Cannot write back: no file path set")

        import json

        data = self._config.model_dump(mode="json", exclude_defaults=True)
        # Pretty-print with 2-space indent
        text = json.dumps(data, indent=2, ensure_ascii=False)
        self._path.write_text(text + "\n", encoding="utf-8")
        logger.info("Config written back to %s", self._path)
