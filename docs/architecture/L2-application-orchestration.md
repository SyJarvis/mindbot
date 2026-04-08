# L2 Application / Orchestration

## Responsibilities

- 负责单轮/多轮会话执行编排。
- 组织 LLM 调用、工具审批与工具执行闭环。
- 维护会话生命周期与回合提交。

## Key Modules

- `src/mindbot/bot.py`
- `src/mindbot/agent/core.py`
- `src/mindbot/agent/agent.py`
- `src/mindbot/agent/orchestrator.py`
- `src/mindbot/agent/streaming.py`
- `src/mindbot/agent/scheduler.py`
- `src/mindbot/agent/approval.py`
- `src/mindbot/agent/input.py`
- `src/mindbot/agent/interrupt.py`
- `src/mindbot/agent/multi_agent.py`
- `src/mindbot/session/store.py`

## Boundary

- 从 L1 接收请求并驱动主执行流。
- 调用 L3/L4/L5 形成结果后返回到 L1。
