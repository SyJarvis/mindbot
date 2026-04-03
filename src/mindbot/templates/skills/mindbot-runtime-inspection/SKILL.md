---
name: mindbot-runtime-inspection
description: 用于查询当前 MindBot 实例的运行时状态，包括配置、memory、journal、已加载 skills 和基础系统资源
when_to_use: 用户询问 MindBot 当前启用了什么配置、skills 数量、memory 或 journal 状态、运行目录、Python/系统资源，或要求做实例巡检
allowed_tools: ["get_mindbot_runtime_info"]
---

# MindBot 运行时巡检技能

## 使用目标
- 当用户询问的是 MindBot 当前实例的“实时状态”而不是静态架构说明时，优先使用本技能。
- 使用 `get_mindbot_runtime_info` 获取结构化结果，再按用户关注点做总结。

## 适用问题
- 当前加载了哪些配置？
- 有多少个内置或用户 skill？
- memory / journal 目录现在是否存在、文件数量是多少？
- 当前 Python 版本、操作系统、工作目录、磁盘空间如何？
- `~/.mindbot` 下的重要文件是否存在？

## 工具使用方式
- 首选调用 `get_mindbot_runtime_info`。
- 输出结果后优先提炼：
  - config 路径与核心配置
  - skills 数量与名称
  - memory / journal 状态
  - 关键系统资源

## 回答原则
- 简单问题只返回用户关心的那一部分，不要机械展开全部 JSON。
- 如果结果里某部分为空、路径不存在或配置加载失败，要明确说明，而不是省略。
- 不主动暴露敏感配置值，只总结安全的运行时信息。

