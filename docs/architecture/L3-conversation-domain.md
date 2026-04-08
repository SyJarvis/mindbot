# L3 Conversation Domain

## Responsibilities

- 定义消息与上下文领域模型。
- 管理上下文分块与 token 预算。
- 处理上下文压缩、检查点与归档相关能力。

## Key Modules

- `src/mindbot/context/models.py`
- `src/mindbot/context/manager.py`
- `src/mindbot/context/compression.py`
- `src/mindbot/context/checkpoint.py`
- `src/mindbot/context/extraction.py`
- `src/mindbot/context/archiver.py`

## Boundary

- 为 L2 提供稳定的对话状态读写能力。
- 不直接负责外部模型调用与通道交互。
