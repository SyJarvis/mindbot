---
name: add-channel
description: MindBot 通道开发指南——BaseChannel 接口契约、注册机制、消息处理流程与完整代码模板
when_to_use: 添加新通道、新增 channel、接入新平台（如 Discord、微信、Slack）
---

# 添加新通道

## 架构定位

通道属于 **L1 接口/传输层**，职责是对接外部消息协议。通道只负责收发消息，通过 `MessageBus` 与 MindBot 主链路交互。

**依赖规则**：通道 → MindBot（L2），禁止通道直接调用 Provider（L5）或工具（L4）。

## 接口契约

继承 `BaseChannel`，实现 4 个方法：

```python
# src/mindbot/channels/base.py
class BaseChannel(ABC):
    name: str = "base"

    def __init__(self, config: Any, bus: MessageBus):
        self.config = config
        self.bus = bus
        self._running = False

    @abstractmethod
    async def start(self) -> None:
        """启动通道，开始监听消息"""

    @abstractmethod
    async def stop(self) -> None:
        """停止通道，释放资源"""

    @abstractmethod
    async def send(self, msg: OutboundMessage) -> None:
        """向用户发送消息"""

    def is_allowed(self, sender_id: str) -> bool:
        """权限检查，可在子类覆盖"""
```

## 注册方式

在 `src/mindbot/channels/manager.py` 的 `_init_channels()` 中添加：

```python
def _init_channels(self) -> None:
    channels_config = getattr(self.config, "channels", None)

    # 复制已有通道的模式
    my_config = getattr(channels_config, "my_channel", None)
    if my_config and getattr(my_config, "enabled", False):
        from mindbot.channels.my_channel import MyChannel
        self.channels["my_channel"] = MyChannel(my_config, self.bus)
```

## 消息处理流程

```python
async def _handle_message(self, sender_id: str, text: str) -> None:
    """收到外部消息后的处理"""
    # 1. 权限检查
    if not self.is_allowed(sender_id):
        return

    # 2. 构造 InboundMessage 通过 bus 发给 MindBot
    await self.bus.publish(InboundMessage(
        channel=self.name,
        sender_id=sender_id,
        content=text,
    ))

    # 3. MindBot 处理完后通过 bus 回调 send() 发送回复
```

## 完整模板

```python
# src/mindbot/channels/my_channel.py
from typing import Any
from mindbot.channels.base import BaseChannel
from mindbot.bus.events import InboundMessage, OutboundMessage

class MyChannel(BaseChannel):
    name: str = "my_channel"

    def __init__(self, config: Any, bus: "MessageBus") -> None:
        super().__init__(config, bus)

    async def start(self) -> None:
        self._running = True
        # 启动外部平台的监听循环

    async def stop(self) -> None:
        self._running = False
        # 断开连接、清理资源

    async def send(self, msg: OutboundMessage) -> None:
        # 将 msg.content 发送到外部平台
        pass

    async def _handle_message(self, sender_id: str, text: str) -> None:
        if not self.is_allowed(sender_id):
            return
        from mindbot.bus.events import InboundMessage
        await self.bus.publish(InboundMessage(
            channel=self.name,
            sender_id=sender_id,
            content=text,
        ))
```

## 配置

在 `settings.json` 的 `channels` 下添加配置：

```json
{
  "channels": {
    "my_channel": {
      "enabled": true,
      "allowed_senders": []
    }
  }
}
```

## 检查清单

- [ ] 继承 `BaseChannel`，实现 `start()` / `stop()` / `send()`
- [ ] 在 `ChannelManager._init_channels()` 中注册
- [ ] 消息通过 `MessageBus` 流转，不直接调用 MindBot
- [ ] 配置在 `settings.json` 的 `channels` 下
- [ ] 测试文件放在 `tests/channels/test_my_channel.py`
