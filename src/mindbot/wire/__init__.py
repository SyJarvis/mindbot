"""Wire 消息队列：异步事件桥接 TurnEngine 与 UI 层。

模块结构：
    wire/__init__.py    Wire 队列类，asyncio.Queue + close sentinel

Wire 坐落在 L1（Interface / Transport），不修改 TurnEngine 或 Agent。
Producer 通过 on_event=wire.send 将 AgentEvent 放入队列；
Consumer 通过 async for event in wire.receive() 迭代消费。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from mindbot.agent.models import AgentEvent, EventType

# 关闭哨兵事件 — 用 identity 判断，不会与正常事件混淆
_CLOSE_SENTINEL = AgentEvent(type=EventType.COMPLETE, timestamp=0, data={"_wire_close": True})


class Wire:
    """异步事件队列，桥接 TurnEngine on_event 回调与 UI 消费者。

    用法::

        wire = Wire()
        # Producer 端（TurnEngine on_event 回调）
        await bot.chat(message, on_event=wire.send)

        # Consumer 端（UI 渲染）
        async for event in wire.receive():
            render(event)
    """

    def __init__(self, *, maxsize: int = 256) -> None:
        self._queue: asyncio.Queue[AgentEvent] = asyncio.Queue(maxsize=maxsize)
        self._closed = False

    # ------------------------------------------------------------------
    # Producer（agent 侧）
    # ------------------------------------------------------------------

    def send(self, event: AgentEvent) -> None:
        """将 AgentEvent 放入队列。

        同步方法，可直接传给 TurnEngine 的 on_event 回调。
        队列满时丢弃最旧事件（背压保护）。
        """
        if self._closed:
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            # 背压保护：丢弃最旧事件，放入最新事件
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self._queue.put_nowait(event)

    def close(self) -> None:
        """发送关闭哨兵，通知消费者结束迭代。"""
        if self._closed:
            return
        self._closed = True
        try:
            self._queue.put_nowait(_CLOSE_SENTINEL)
        except asyncio.QueueFull:
            # 队列满时强制清空一个位置
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self._queue.put_nowait(_CLOSE_SENTINEL)

    # ------------------------------------------------------------------
    # Consumer（UI 侧）
    # ------------------------------------------------------------------

    async def receive(self) -> AsyncIterator[AgentEvent]:
        """异步迭代事件流。遇到关闭哨兵时停止。"""
        while True:
            event = await self._queue.get()
            if event is _CLOSE_SENTINEL:
                return
            yield event

    @property
    def is_closed(self) -> bool:
        """队列是否已关闭。"""
        return self._closed
