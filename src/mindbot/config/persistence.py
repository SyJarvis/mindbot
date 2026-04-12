"""配置持久化 - Phase 3"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from mindbot.config.bus import ConfigBus

logger = logging.getLogger(__name__)


class ConfigPersistence:
    """配置持久化器"""

    def __init__(
        self,
        bus: ConfigBus,
        path: Path,
        save_interval: float = 60.0,  # 每分钟保存
    ):
        self.bus = bus
        self.path = path
        self.save_interval = save_interval
        self._running = False
        self._version_at_save = 0
        self._save_task: asyncio.Task | None = None

    async def start(self) -> None:
        """启动自动保存"""
        self._running = True
        self._save_task = asyncio.create_task(self._save_loop())
        logger.info(f"Config persistence started, saving to {self.path}")

    async def _save_loop(self) -> None:
        """保存循环"""
        while self._running:
            await asyncio.sleep(self.save_interval)
            if self._version_at_save < self.bus.version:
                await self._save()

    async def _save(self) -> None:
        """保存到磁盘"""
        try:
            snapshot = {
                scope: {
                    k: self._serialize(v)
                    for k, v in items.items()
                }
                for scope, items in self.bus._store.items()
            }

            # 原子写入
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix('.tmp')
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(snapshot, f, default=str, indent=2, ensure_ascii=False)
            tmp.replace(self.path)

            self._version_at_save = self.bus.version
            logger.debug(f"Config saved to {self.path}")
        except Exception:
            logger.exception("Failed to save config")

    def _serialize(self, value: Any) -> Any:
        """序列化配置值"""
        if hasattr(value, 'to_dict'):
            return value.to_dict()
        if hasattr(value, '__dict__'):
            return value.__dict__
        return value

    async def load(self) -> None:
        """从磁盘加载"""
        if not self.path.exists():
            logger.info(f"No config file found at {self.path}, starting fresh")
            return

        try:
            with open(self.path, encoding='utf-8') as f:
                data = json.load(f)

            for scope, items in data.items():
                for key, value in items.items():
                    await self.bus.set(scope, key, value)

            self._version_at_save = self.bus.version
            logger.info(f"Config loaded from {self.path}")
        except Exception:
            logger.exception("Failed to load config")

    async def stop(self) -> None:
        """停止自动保存并执行一次保存"""
        self._running = False
        if self._save_task:
            self._save_task.cancel()
            try:
                await self._save_task
            except asyncio.CancelledError:
                pass
        # 最后保存一次
        await self._save()

    async def force_save(self) -> None:
        """强制保存"""
        await self._save()
