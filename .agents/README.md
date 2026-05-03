# .agents/ — MindBot AI 编程工具配置

本目录为 [OpenCode](https://opencode.ai)、[Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview)、Cursor 等 AI 编程工具预配置了项目 Skills，开箱即用。

---

## 目录结构

```
.agents/
├── README.md              # 本文件 — 工具使用说明
├── skills/                # 可复用技能模块
│   ├── add-channel/       # MindBot 通道开发指南
│   ├── add-provider/      # LLM Provider 开发指南
│   ├── add-tool/          # 工具开发指南
│   ├── add-skill/         # Skill 创建指南
│   ├── coding-guidelines/ # LLM 编码行为准则
│   ├── compute/           # 数学计算工具
│   ├── skill-creator/     # 通用 Skill 创建器
│   ├── test-patterns/     # 测试编写规范
│   └── xlsx/              # 电子表格操作
```

---

## 快速开始

### OpenCode

在本仓库目录下启动 OpenCode，Skills 自动加载：

```bash
opencode
```

通过自然语言或斜杠命令调用 Skill：

```
/add-channel 为 MindBot 添加一个 Discord 通道
```

或直接描述任务，OpenCode 会自动匹配对应 Skill。

### Claude Code

#### 方式一：迁移配置（推荐）

```bash
# 1. 创建 Claude Code 目录
mkdir -p .claude/skills

# 2. 复制项目指令
cp AGENTS.md CLAUDE.md

# 3. 复制 Skills
cp -r .agents/skills/* .claude/skills/
```

#### 方式二：直接启动

```bash
claude
```

启动后在对话中使用斜杠命令或自然语言调用 Skill。

### Cursor / 其他工具

将 `AGENTS.md` 的内容复制到项目的 AI Rules / System Prompt 配置中，Skills 目录按工具要求放置。

---

## Skills 一览

### 开发指南类

| Skill | 说明 | 适用场景 |
|:------|:-----|:---------|
| `add-channel` | MindBot 通道开发指南 | 接入新平台（Discord、微信等），提供 BaseChannel 接口契约与完整代码模板 |
| `add-provider` | LLM Provider 开发指南 | 接入新 LLM 服务，提供 Provider 基类接口、Param 配置与 Factory 注册机制 |
| `add-tool` | 工具开发指南 | 为 MindBot 添加新工具，涵盖 Tool 模型定义、handler 编写与注册流程 |
| `add-skill` | Skill 创建指南 | 创建 MindBot 专属 Skill，包含格式规范、加载机制与存放规则 |
| `test-patterns` | 测试编写规范 | 编写 MindBot 测试，涵盖 FakeLLM、AsyncMock、fixture 约定 |

### 通用能力类

| Skill | 说明 | 适用场景 |
|:------|:-----|:---------|
| `coding-guidelines` | LLM 编码行为准则 | 减少常见编码错误——先思考再编码、简洁优先、精准修改、目标驱动执行 |
| `skill-creator` | 通用 Skill 创建器 | 创建适用于任何 AI 工具的 Skill，含 6 步创建流程与设计模式 |
| `compute` | 数学计算工具 | 数学表达式求值、sigmoid、阶乘、斐波那契、GCD/LCM 等 |
| `xlsx` | 电子表格操作 | Excel 文件创建、编辑、公式计算与财务建模 |

### 内置 Skills（随 MindBot 安装）

位于 `src/mindbot/templates/skills/`，在 MindBot 运行时自动加载：

| Skill | 说明 |
|:------|:-----|
| `mindbot-self-knowledge` | MindBot 自身架构、配置与能力边界的自说明知识包 |
| `mindbot-runtime-inspection` | 查询当前实例运行时状态（配置、skills、memory、系统资源） |
| `system-basic-info` | 查看运行环境基础信息（OS、Python 版本、工作目录） |

---

## 各工具目录结构映射

| 组件 | OpenCode | Claude Code | 说明 |
|:-----|:---------|:------------|:-----|
| 项目指令 | `AGENTS.md` | `CLAUDE.md` | 自动加载的项目规范 |
| Skills | `.agents/skills/` | `.claude/skills/` | 可复用行为模块 |
| 配置 | `.agents/settings.json` | `.claude/settings.json` | Hook / 权限配置 |

**格式兼容性**：所有 Skill 均使用 `SKILL.md`（YAML frontmatter + Markdown），各工具完全兼容。

---

## Skill 调用方式

三种方式，按需选择：

**1. 斜杠命令**（明确指定）

```
/add-channel 为 MindBot 添加一个 Slack 通道
```

**2. 自然语言点名**

```
请使用 add-provider 技能帮我接入 Gemini 模型
```

**3. 自动匹配**（描述任务，AI 自动选择）

```
我需要为 MindBot 添加一个新的工具，用于查询天气
```

---

## 创建新 Skill

使用 `skill-creator` 或 `add-skill` 技能快速创建：

```
/skill-creator 创建一个代码审查 Skill
```

Skill 标准结构：

```
my-skill/
├── SKILL.md          # 必须 — YAML frontmatter + 执行流程
├── scripts/          # 可选 — 辅助脚本
├── references/       # 可选 — 参考资料
└── LICENSE.txt       # 可选 — 许可证
```

`SKILL.md` 最小模板：

```markdown
---
name: my-skill
description: 一句话描述 Skill 功能
---

# Skill 标题

## 使用目标
描述 Skill 的目标和使用场景。

## 执行流程
1. 步骤一
2. 步骤二
3. 步骤三
```

---

## 常见问题

<details>
<summary><b>AGENTS.md、Skills 有什么区别？</b></summary>

| 维度 | AGENTS.md | Skills |
|:-----|:----------|:-------|
| 作用 | 项目级自定义规范，定义架构规则和开发约束 | 特定任务的执行流程和行为指导 |
| 加载方式 | 自动加载，对所有对话生效 | 按需加载，调用时才生效 |
| 内容 | 五层架构、铁律、目录职责、测试约定 | 具体任务的步骤、模板、验证标准 |

两者配合使用：AGENTS.md 定义"怎么做才对"，Skills 定义"怎么一步步做完"。

</details>

<details>
<summary><b>.agents/skills/ 和 src/mindbot/templates/skills/ 有什么区别？</b></summary>

- **`.agents/skills/`**：面向 AI 编程工具的开发指南，帮助开发者在 OpenCode/Claude Code 中扩展 MindBot
- **`src/mindbot/templates/skills/`**：MindBot 运行时内置技能，随应用安装自动加载，在用户对话中按需激活

</details>

<details>
<summary><b>Skill 机制 vs 硬编码？</b></summary>

- **用 Skill**：提示层面的知识注入、可插拔的行为指导、用户可自定义的领域知识
- **硬编码**：核心架构逻辑、不可变的铁律、性能关键路径

</details>
