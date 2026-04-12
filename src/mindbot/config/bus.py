"""配置事件总线 - Phase 1"""

import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class ConfigBus:
    """内存配置总线 - 零延迟读写"""

    def __init__(self):
        self._store: dict[str, dict[str, Any]] = defaultdict(dict)
        self._subscribers: dict[tuple[str, str], list[Callable]] = defaultdict(list)
        self._lock = asyncio.Lock()
        self._version = 0

    async def set(self, scope: str, key: str, value: Any) -> None:
        """设置配置，立即通知"""
        async with self._lock:
            self._version += 1
            old = self._store[scope].get(key)
            self._store[scope][key] = value

        # 异步通知
        asyncio.create_task(self._notify(scope, key, old, value))

    async def get(self, scope: str, key: str, default: Any = None) -> Any:
        """获取配置"""
        return self._store[scope].get(key, default)

    def subscribe(self, scope: str, key: str, callback: Callable) -> None:
        """订阅变更"""
        self._subscribers[(scope, key)].append(callback)

    def unsubscribe(self, scope: str, key: str, callback: Callable) -> None:
        """取消订阅变更"""
        if (scope, key) in self._subscribers:
            self._subscribers[(scope, key)] = [
                cb for cb in self._subscribers[(scope, key)] if cb != callback
            ]

    async def _notify(self, scope: str, key: str, old: Any, new: Any) -> None:
        """通知订阅者"""
        for cb in self._subscribers.get((scope, key), []):
            try:
                result = cb(old, new)
                # 如果回调是协程函数，await它
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception(f"Config change callback failed for {scope}.{key}")

    @property
    def version(self) -> int:
        """获取当前版本号"""
        return self._version

    def get_scope(self, scope: str) -> dict[str, Any]:
        """获取整个 scope 的配置"""
        return dict(self._store[scope])

    async def delete(self, scope: str, key: str) -> bool:
        """删除配置"""
        async with self._lock:
            if scope in self._store and key in self._store[scope]:
                old = self._store[scope].pop(key)
                self._version += 1
                asyncio.create_task(self._notify(scope, key, old, None))
                return True
            return False
