---
title: Skills 机制
---

# Skills 机制

Skills 是 MindBot 的 Prompt 层技能注入机制，通过 `SKILL.md` 文件为 Agent 提供领域知识、流程指导和约束提示。

## 什么是 Skills

每个 Skill 由一个 `SKILL.md` 文件定义，包含以下内容：

- **metadata**：技能的元信息，用于匹配触发条件
- **摘要**：简短的技能描述，默认注入到 prompt 中
- **正文**：完整的知识内容，仅在命中时注入

Skill 负责知识、流程和约束提示；Tool 则负责真实的动作执行。两者互补，共同构成 Agent 的完整能力。

## 目录结构

### 内置 Skills

MindBot 自带的内置 Skills 位于代码仓库中：

```
mindbot/skills/<skill-name>/SKILL.md
```

### 用户自定义 Skills

用户创建的自定义 Skills 位于数据目录中：

```
~/.mindbot/skills/<skill-name>/SKILL.md
```

MindBot 会自动扫描这两个目录，加载所有可用的 Skills。

## 工作原理

1. **摘要阶段**：每轮对话开始时，MindBot 将所有 Skill 的摘要注入到 prompt 中（受 `max_visible` 限制）
2. **匹配阶段**：当用户问题命中某个 Skill 的 metadata 时，MindBot 自动将该 Skill 的完整正文注入到 prompt 中
3. **加载限制**：为控制 Token 消耗，每轮对话最多展开 `max_detail_load` 个 Skill 的正文

## 配置选项

Skills 的行为通过 `settings.json` 中的 `skills` 节进行配置：

```jsonc
{
  "skills": {
    "enabled": true,
    "skill_dirs": [],
    "always_include": ["mindbot-self-knowledge"],
    "max_visible": 8,
    "max_detail_load": 2,
    "trigger_mode": "metadata-match"
  }
}
```

### 配置项说明

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enabled` | bool | `true` | 是否启用 Skills 机制 |
| `skill_dirs` | list | `[]` | 额外的 Skill 搜索目录列表 |
| `always_include` | list | `["mindbot-self-knowledge"]` | 始终注入正文的 Skill 名称列表（不依赖匹配） |
| `max_visible` | int | `8` | prompt 中最多显示的 Skill 摘要数量 |
| `max_detail_load` | int | `2` | 每轮对话最多展开的 Skill 正文数量 |
| `trigger_mode` | string | `"metadata-match"` | 触发模式：`metadata-match` 表示按元数据匹配触发 |

## 创建自定义 Skill

1. 在 `~/.mindbot/skills/` 下创建目录：

```bash
mkdir -p ~/.mindbot/skills/my-custom-skill
```

2. 创建 `SKILL.md` 文件，包含 metadata 摘要和正文：

```markdown
---
name: my-custom-skill
description: 自定义技能描述
keywords: [关键词1, 关键词2]
---

# 我的自定义技能

简短摘要（默认注入 prompt）

---

完整正文内容（命中 metadata 时才注入 prompt）
包含详细的知识、流程和约束说明...
```

3. 重启 MindBot，新 Skill 将自动加载。

## 配额与上下文

Skills 的 Token 占用受 `context.blocks` 配置控制：

```jsonc
{
  "context": {
    "max_tokens": 8000,
    "blocks": {
      "skills_overview": 640,
      "skills_detail": 1200
    }
  }
}
```

- `skills_overview`：摘要区域的最大 Token 预算
- `skills_detail`：正文区域的最大 Token 预算

如果 Skill 内容超出预算，MindBot 会自动截断。

## 下一步

- [示例代码](examples.md) -- 通过示例深入了解 MindBot 的各项能力
- [多 Agent 编排](multi-agent.md) -- 学习如何为不同 Agent 配置不同的工具和提示词
