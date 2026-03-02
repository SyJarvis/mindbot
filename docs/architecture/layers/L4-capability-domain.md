# L4 Capability Domain

## Responsibilities

- 提供可编排调用的能力子域（工具、记忆、路由、生成）。
- 对上暴露统一能力接口，对下复用基础设施适配。
- 保持能力实现与业务编排解耦。

## Key Modules

- `src/mindbot/capability/facade.py`
- `src/mindbot/capability/registry.py`
- `src/mindbot/capability/backends/tooling/models.py`
- `src/mindbot/capability/backends/tooling/registry.py`
- `src/mindbot/capability/backends/tooling/executor.py`
- `src/mindbot/memory/manager.py`
- `src/mindbot/memory/searcher.py`
- `src/mindbot/memory/indexer.py`
- `src/mindbot/memory/compaction.py`
- `src/mindbot/routing/router.py`
- `src/mindbot/routing/adapter.py`
- `src/mindbot/routing/endpoint.py`
- `src/mindbot/generation/tool_generator.py`
- `src/mindbot/generation/executor.py`
- `src/mindbot/generation/registry.py`

## Boundary

- 接收 L2 的能力调用请求并返回结构化结果。
- 不直接处理通道层协议和用户交互细节。
