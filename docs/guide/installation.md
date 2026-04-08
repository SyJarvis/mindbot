---
title: 安装指南
---

# 安装指南

## 环境要求

| 要求 | 版本 |
|------|------|
| Python | >= 3.10 |
| asyncio | 内置 |

## 安装步骤

1. 克隆仓库：

```bash
git clone https://github.com/SyJarvis/mindbot.git
cd mindbot
```

2. 以开发模式安装：

```bash
pip install -e .
```

安装完成后，`mindbot` 命令即可使用。

## 数据目录结构

首次运行 `mindbot generate-config` 后，MindBot 会在用户主目录下创建 `~/.mindbot/` 数据目录，结构如下：

```
~/.mindbot/
├── settings.json         # 用户配置（JSON/JSONC）
├── SYSTEM.md             # 系统提示词
├── skills/               # 自定义技能
├── memory/               # Markdown 记忆存储
├── history/              # CLI 历史记录
├── workspace/            # 默认工作空间
├── data/
│   ├── memory.db         # 记忆数据库
│   └── journal/          # 会话记录
├── logs/                 # 日志文件
└── sessions/             # 会话存储
```

## 首次配置初始化

```bash
mindbot generate-config
```

该命令会自动创建 `~/.mindbot/settings.json` 和 `~/.mindbot/SYSTEM.md`。你也可以使用别名：

```bash
mindbot onboard
```

## 配置迁移

如果你有旧版 YAML 格式的配置文件，可以使用迁移命令将其转换为 JSON/JSONC 格式：

```bash
mindbot config migrate
```

> **注意**：YAML 配置格式已弃用，请尽快迁移到 JSON/JSONC 格式。

## 下一步

完成安装后，请阅读 [快速开始](quickstart.md) 完成首次配置并运行第一个对话。
