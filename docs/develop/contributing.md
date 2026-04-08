# 贡献指南

感谢你对 MindBot 的关注！本文档介绍如何参与开发。

## 开发环境

```bash
git clone https://github.com/SyJarvis/mindbot.git
cd mindbot
pip install -e .
```

## 代码规范

- **Lint**: `ruff check .`
- **类型检查**: `mypy src/`
- **测试**: `pytest tests/ -m 'not integration' -q`
- **文档**: `mkdocs serve` 本地预览

详细规范参见 `AGENTS.md` 和 `skills/` 目录。

## 提交规范

使用 [Conventional Commits](https://www.conventionalcommits.org/) 格式：

```
feat: add new tool
fix: resolve memory leak
docs: update api reference
refactor: simplify context manager
test: add turn engine tests
```

## 分支策略

详见 [Git 指南](git-guide.md)。

## 测试要求

- 所有新功能必须包含测试
- 异步函数使用 `@pytest.mark.asyncio`
- 外部依赖必须 mock
- 运行 `pytest --cov=src/mindbot` 检查覆盖率

## 架构约束

修改代码时请遵循以下约束（详见 `AGENTS.md`）：

- **主链路不可绕过** — 所有对话必须经过 `Agent.chat()`
- **全异步** — 公开方法必须是 `async def`
- **层依赖方向** — L1 → L2 → (L3, L4) → L5，不可反转
