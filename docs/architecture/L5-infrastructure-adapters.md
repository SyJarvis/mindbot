# L5 Infrastructure Adapters

## Responsibilities

- 对接外部模型服务、存储与系统能力。
- 封装 API/存储细节，向上提供稳定适配接口。
- 承载与运行环境相关的具体实现。

## Key Modules

- `src/mindbot/providers/base.py`
- `src/mindbot/providers/adapter.py`
- `src/mindbot/providers/factory.py`
- `src/mindbot/providers/openai/provider.py`
- `src/mindbot/providers/ollama/provider.py`
- `src/mindbot/providers/transformers/provider.py`
- `src/mindbot/providers/llama_capp/provider.py`
- `src/mindbot/memory/storage.py`
- `src/mindbot/memory/markdown.py`
- `src/mindbot/cron/service.py`

## Boundary

- 向上为 L2/L4 提供外部依赖的可调用实现。
- 不承担业务编排与会话策略决策。
