"""配置同步 - Phase 4 (可选)"""

import asyncio
import logging
from typing import Any, Protocol

from mindbot.config.bus import ConfigBus

logger = logging.getLogger(__name__)


class SyncBackend(Protocol):
    """同步后端协议"""

    async def get_version(self) -> int:
        """获取远程版本号"""
        ...

    async def get_delta(self, since: int) -> list[tuple[str, str, Any]]:
        """获取增量配置"""
        ...

    async def publish(self, scope: str, key: str, value: Any) -> None:
        """发布配置变更"""
        ...


class ConfigSync:
    """配置同步器 - 多实例场景"""

    def __init__(
        self,
        bus: ConfigBus,
        backend: SyncBackend | None = None,
        sync_interval: float = 5.0,
    ):
        self.bus = bus
        self.backend = backend
        self.sync_interval = sync_interval
        self._remote_version = 0
        self._running = False
        self._sync_task: asyncio.Task | None = None

    async def start(self) -> None:
        """启动同步循环"""
        if self.backend is None:
            logger.warning("No sync backend configured, skipping sync")
            return

        self._running = True
        self._sync_task = asyncio.create_task(self._sync_loop())
        logger.info("Config sync started")

    async def _sync_loop(self) -> None:
        """同步循环"""
        while self._running:
            try:
                await self._sync_once()
            except Exception:
                logger.exception("Sync error")
            await asyncio.sleep(self.sync_interval)

    async def _sync_once(self) -> None:
        """执行一次同步"""
        if self.backend is None:
            return

        # 查询远程版本号
        remote_version = await self.backend.get_version()

        if remote_version > self.bus.version:
            # 拉取增量配置
            delta = await self.backend.get_delta(self.bus.version)
            for scope, key, value in delta:
                await self.bus.set(scope, key, value)
            self._remote_version = remote_version
            logger.debug(f"Synced {len(delta)} config items")

    async def stop(self) -> None:
        """停止同步"""
        self._running = False
        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
        logger.info("Config sync stopped")


class MemorySyncBackend:
    """内存同步后端 - 用于单机多实例测试"""

    def __init__(self):
        self._version = 0
        self._store: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def get_version(self) -> int:
        return self._version

    async def get_delta(self, since: int) -> list[tuple[str, str, Any]]:
        # 简化实现：返回所有数据
        result = []
        for scope, items in self._store.items():
            for key, value in items.items():
                result.append((scope, key, value))
        return result

    async def publish(self, scope: str, key: str, value: Any) -> None:
        async with self._lock:
            if scope not in self._store:
                self._store[scope] = {}
            self._store[scope][key] = value
            self._version += 1
