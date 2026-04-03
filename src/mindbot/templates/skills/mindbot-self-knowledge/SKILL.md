---
name: mindbot-self-knowledge
description: 提供 MindBot 自身架构、配置、目录和能力边界的自说明知识包
when_to_use: 用户询问 MindBot 是什么、如何配置、目录结构、examples 用法、tool 与 skill 的区别、或当前实现边界
allowed_tools: ["get_mindbot_runtime_info"]
---

# MindBot 自说明技能

## 使用目标
- 当用户问题直接涉及 MindBot 本身时，优先依赖本技能组织回答。
- 先解释 MindBot 当前代码库里的真实实现，再说明仍未完成或尚未接入的能力。
- 避免把未来规划说成已经完成的功能。

## 核心事实
- MindBot 是一个基于 Python 和 asyncio 的模块化 Agent 框架。
- 主链路入口围绕 `MindBot`、`MindAgent`、`Agent` 组织：
  - `MindBot` 提供面向外部的统一产品级入口。
  - `MindAgent` 负责主代理与子代理编排。
  - `Agent` 是实际执行单轮对话、上下文装配、工具协同的核心运行体。
- 现阶段真实动作执行主要由 `tool` 链路承担：
  - provider tool schema
  - tool call
  - capability facade/tool backend
- `skill` 的定位是 prompt-level guidance：
  - 提供知识、流程、约束和上下文模板
  - 不直接执行动作
  - 不替代 tool/function call

## 配置与目录
- 全局工作目录默认位于 `~/.mindbot/`。
- 典型文件与目录包括：
  - `~/.mindbot/settings.json`：运行配置
  - `~/.mindbot/SYSTEM.md`：系统提示词
  - `~/.mindbot/skills/`：用户自定义技能目录
  - `~/.mindbot/memory/`、`~/.mindbot/history/`、`~/.mindbot/cron/`：工作目录子结构
- `mindbot generate-config` 会初始化这些文件和目录。

## 回答原则
- 如果用户问“怎么配置”，优先说明 `settings.json`、provider、memory、context、skills 等配置段。
- 如果用户问的是“当前这次实例实际加载了什么配置 / 有多少 skills / memory 和 journal 目录现在是什么状态 / 当前系统资源怎么样”，应调用 `get_mindbot_runtime_info` 获取实时结果，不要只根据静态知识猜测。
- 如果用户问“怎么扩展”，优先说明：
  - 新增 tool 是动作扩展
  - 新增 `SKILL.md` 是 prompt 能力扩展
- 如果用户问“当前支持什么”，要区分：
  - 已实现：tool、memory、routing、channels、dynamic tools 等
  - 预留但未完整落地：更完整的 `CapabilityType.SKILL` backend、MCP backend 等

## 边界说明
- 不要声称所有仓库中的实验目录都属于 MindBot 稳定 API。
- 不要把设计文档中的未来方案当作已上线行为。
- 如果用户需要具体代码位置，应优先引用实际文件路径，而不是泛泛描述。
- 如果涉及运行时状态、配置文件是否存在、skills 数量、memory/journal 文件数量等动态信息，应优先使用工具查询。

