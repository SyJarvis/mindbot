---
name: add-skill
description: MindBot Skill 创建指南——通用创建流程参考 .agents/skills/skill-creator/，本 Skill 补充 mindbot 特有的格式、加载机制与存放规则
when_to_use: 创建新技能、新增 skill、编写可复用的提示注入知识包
---

# 创建新 Skill

> **通用 Skill 创建流程**（理解需求→规划→初始化→编辑→打包→迭代）请参考：
> [skill-creator](../skill-creator/SKILL.md)
>
> 包含完整的 6 步创建流程、设计原则（自由度控制、渐进加载 Pattern）、scripts/references 的使用指南。
>
> 以下仅补充 **mindbot 特有的格式与机制**。

## 什么是 Skill

Skill 是**提示层面的知识注入包**，不是可执行代码。通过 `SkillLoader` 加载、`SkillSelector` 匹配、渲染后注入 LLM 的 system prompt。

## Frontmatter 字段（mindbot 扩展）

mindbot 在标准 `name` + `description` 基础上扩展了两个字段：

| 字段 | 必须 | 说明 |
|------|------|------|
| `name` | 是 | 技能唯一标识，小写 + 连字符 |
| `description` | 是 | 描述功能 + 触发场景，用于 SkillSelector 匹配 |
| `when_to_use` | 否 | 触发条件描述，第二级渐进加载时可见 |
| `allowed_tools` | 否 | 该技能允许使用的工具列表 |

## 渐进加载机制

Skill 分三级加载，控制 token 消耗：

1. **Summary**：仅 `name` + `description`，用于选择阶段
2. **Metadata**：+ `when_to_use`，用于确认匹配
3. **Full Body**：完整 SKILL.md 内容 + references，注入 prompt

## 存放位置

| 位置 | 路径 | 用途 |
|------|------|------|
| 内置 Skill | `src/mindbot/templates/skills/` | 随代码发布 |
| 用户 Skill | `~/.mindbot/skills/` | 用户自定义 |
| 项目 Skill | 项目目录下 `skills/` | 项目特定 |

## SKILL.md 模板

```markdown
---
name: my-skill
description: 一句话描述功能 + 什么时候触发
when_to_use: 具体的触发条件
allowed_tools: ["tool1"]
---

# 技能标题

## 用途
解决什么问题

## 核心信息
具体知识、工作流、约束

## 参考文档
- [详细指南](references/detailed.md)
```

## 检查清单

- [ ] frontmatter 包含 `name`、`description`（必填）
- [ ] `name` 使用小写 + 连字符格式
- [ ] `description` 包含功能描述和触发场景
- [ ] body 简洁，详细内容放 `references/`
- [ ] 可执行脚本放 `scripts/`
