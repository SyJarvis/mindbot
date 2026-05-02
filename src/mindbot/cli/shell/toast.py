"""非侵入式 Toast 通知。"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Literal


@dataclass
class _ToastEntry:
    topic: str | None
    message: str
    expires_at: float


_toast_queues: dict[Literal["left", "right"], deque[_ToastEntry]] = {
    "left": deque(),
    "right": deque(),
}


def toast(
    message: str,
    *,
    duration: float = 5.0,
    topic: str | None = None,
    position: Literal["left", "right"] = "left",
) -> None:
    """发送 Toast 通知，显示在工具栏中。"""
    queue = _toast_queues[position]
    entry = _ToastEntry(
        topic=topic,
        message=message,
        expires_at=time.monotonic() + max(duration, 1.0),
    )
    # 同 topic 替换已有 Toast
    if topic is not None:
        for existing in list(queue):
            if existing.topic == topic:
                queue.remove(existing)
    queue.append(entry)


def current_toast(position: Literal["left", "right"] = "left") -> _ToastEntry | None:
    """获取当前可见的 Toast（过期自动清除）。"""
    queue = _toast_queues[position]
    now = time.monotonic()
    while queue and queue[0].expires_at <= now:
        queue.popleft()
    return queue[0] if queue else None
