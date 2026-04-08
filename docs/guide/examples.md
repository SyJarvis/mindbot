---
title: 示例代码
---

# 示例代码

MindBot 提供了 11 个示例程序，涵盖了从基础对话到多 Agent 编排的各种用法。示例代码位于项目根目录的 `examples/` 目录下。

## 运行方式

直接使用 Python 运行示例文件：

```bash
python examples/01_simple_chat.py
```

或使用模块方式运行：

```bash
python -m examples.01_simple_chat
```

运行前请确保已完成 [安装](installation.md) 和 [配置](quickstart.md)。

## 示例列表

| 示例 | 文件 | 说明 |
|------|------|------|
| 01 | `01_simple_chat.py` | 单轮对话 |
| 02 | `02_multi_turn.py` | 多轮会话与 `session_id` |
| 03 | `03_streaming.py` | 流式输出 |
| 04 | `04_event_callbacks.py` | 事件回调 |
| 05 | `05_system_prompt.py` | 系统提示词 |
| 06 | `06_tool_approval.py` | 工具审批 |
| 07 | `07_multi_agent.py` | 多 Agent 编排 |
| 08 | `08_config_from_code.py` | 纯代码配置 |
| 09 | `09_tool_whitelist.py` | 工具白名单 |
| 10 | `10_child_agent.py` | 子 Agent |
| 11 | `11_tool_example.py` | `@tool` 工具定义 |

## 示例简介

### 01 - 单轮对话

最基础的用法，向 MindBot 发送一条消息并获取回复。

### 02 - 多轮会话

演示如何使用 `session_id` 维持多轮对话上下文，Agent 会记住之前的对话内容。

### 03 - 流式输出

演示如何接收流式响应，实时获取 Agent 的输出内容。

### 04 - 事件回调

演示如何通过 `on_event` 回调监听 Agent 执行过程中的各类事件（如工具调用、思考过程等）。

### 05 - 系统提示词

演示如何自定义系统提示词，引导 Agent 以特定角色或风格回答问题。

### 06 - 工具审批

演示 MindBot 的工具确认机制，包括安全级别配置和白名单管理。

### 07 - 多 Agent 编排

演示使用 `MultiAgentOrchestrator` 构建多个专长不同的 Agent，支持顺序和并行两种执行模式。详见 [多 Agent 编排](multi-agent.md)。

### 08 - 纯代码配置

演示不依赖配置文件，完全通过 Python 代码构建 MindBot 实例。

### 09 - 工具白名单

演示如何配置工具白名单，精细控制 Agent 可使用的工具范围。

### 10 - 子 Agent

演示通过 `MindAgent` 的 Supervisor 模式管理子 Agent，每个子 Agent 拥有独立的系统提示词和工具集。详见 [多 Agent 编排](multi-agent.md)。

### 11 - 工具定义

演示如何使用 `@tool` 装饰器自定义工具，并将其注册给 Agent 使用。

## 下一步

- [多 Agent 编排](multi-agent.md) -- 深入学习示例 07 和示例 10 的相关概念
- [Skills 机制](skills.md) -- 了解如何为 Agent 注入专业知识
