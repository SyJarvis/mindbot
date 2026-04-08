# MindBot Layered Docs

本目录按 `src/mindbot` 当前实现分层整理，先提供简版说明，后续逐层补充详细设计。

## Layers

- L1 Interface / Transport
- L2 Application / Orchestration
- L3 Conversation Domain
- L4 Capability Domain
- L5 Infrastructure Adapters

## Unified Execution Flow (ASCII)

```text
UserInput
   |
   v
[L1 Interface/Transport]
channels/* + bus/* + cli/*
   |
   v
[L2 Application/Orchestration]
MindBot.chat() -> Agent/MindAgent -> Scheduler.assemble()
   |
   v
[L3 Conversation Domain]
context manager/models/compression
   |
   v
[L5 Provider Adapters]
providers/* (LLM inference)
   |
   +--> if tool_calls --> [L2 Approval] --> [L4 Capability Tool Executor]
   |                                           capability/backends/tooling/*
   v
[L2 Commit]
Scheduler.commit() + memory append
   |
   v
AssistantResponse
```

## Layer Files

- `L1-interface-transport.md`
- `L2-application-orchestration.md`
- `L3-conversation-domain.md`
- `L4-capability-domain.md`
- `L5-infrastructure-adapters.md`
