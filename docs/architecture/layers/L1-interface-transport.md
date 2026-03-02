# L1 Interface / Transport

## Responsibilities

- 接收外部输入并转换为内部消息。
- 承载通道协议适配与消息收发。
- 不负责业务推理与工具决策。

## Key Modules

- `src/mindbot/channels/base.py`
- `src/mindbot/channels/manager.py`
- `src/mindbot/channels/cli.py`
- `src/mindbot/channels/http.py`
- `src/mindbot/channels/feishu.py`
- `src/mindbot/bus/events.py`
- `src/mindbot/bus/queue.py`
- `src/mindbot/cli/__init__.py`

## Boundary

- 向上游（用户/外部系统）暴露交互入口。
- 向下游（L2）交付标准化输入与事件。
