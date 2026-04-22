# MindBot 配置指南

本文档详细介绍 MindBot 的配置文件 `settings.json` 及配置目录结构。

---

## 目录结构

```
~/.mindbot/
├── settings.json          # 主配置文件
├── SYSTEM.md              # 系统提示文件（角色设定）
├── data/
│   ├── memory.db          # 记忆数据库（SQLite，包含短期/长期记忆）
│   ├── memory/
│   │   ├── long_term/     # 长期记忆 markdown 源文件
│   │   │   ├── processed/ # 处理后的分类文件
│   │   │   └── *.md       # 原始记忆文件
│   │   └── short_term/    # 短期记忆 markdown 源文件（自动清理）
│   └── journal/           # Session journal（对话历史 JSONL）
├── skills/
│   └── <skill-name>/      # 自定义技能目录
│       └── SKILL.md       # 技能定义文件
├── tools/                 # 自定义工具目录
├── workspace/             # 默认工作空间
├── cron/                  # 定时任务配置
└── history/               # 命令历史
```

### 目录说明

| 目录/文件 | 用途 | 是否必需 |
|----------|------|---------|
| `settings.json` | 主配置文件 | ✅ 必需 |
| `SYSTEM.md` | 系统提示（角色设定） | ❌ 可选 |
| `data/memory.db` | 记忆数据库 | ✅ 必需（启用记忆时） |
| `data/memory/long_term/` | 长期记忆源文件 | ❌ 可选 |
| `data/journal/` | 对话历史记录 | ❌ 可选 |
| `skills/` | 自定义技能 | ❌ 可选 |
| `workspace/` | 文件操作工作空间 | ✅ 必需 |

---

## settings.json 配置字段

### 根级配置

```json
{
  "providers": { ... },
  "agent": { ... },
  "routing": { ... },
  "memory": { ... },
  "skills": { ... },
  "context": { ... },
  "session_journal": { ... },
  "multimodal": { ... },
  "channels": { ... },
  "debug": { ... },
  "tool_models": { ... }
}
```

---

## providers（模型提供商）

配置 LLM 模型提供商，支持多个提供商和负载均衡。

### 结构

```json
{
  "providers": {
    "<实例名称>": {
      "type": "openai | ollama | transformers",
      "strategy": "round-robin | random | priority",
      "endpoints": [
        {
          "base_url": "http://...",
          "api_key": "...",
          "weight": 1,
          "models": [
            {
              "id": "model-name",
              "role": "chat | embed",
              "level": "low | medium | high",
              "vision": false,
              "tool": true,
              "enabled": true
            }
          ]
        }
      ]
    }
  }
}
```

### 字段说明

| 字段 | 类型 | 默认值 | 说明 |
|-----|------|--------|------|
| `type` | string | `""` | 驱动类型：`openai`、`ollama`、`transformers`，空则自动推断 |
| `strategy` | string | `"round-robin"` | 负载均衡策略：轮询/随机/优先级 |
| `endpoints` | array | `[]` | API 端点列表 |

### EndpointConfig 字段

| 字段 | 类型 | 默认值 | 说明 |
|-----|------|--------|------|
| `base_url` | string | - | API 基础 URL（必需） |
| `api_key` | string | `""` | API 密钥 |
| `weight` | int | `1` | 负载均衡权重（越高越多请求） |
| `models` | array | `[]` | 该端点可用模型列表 |

### ModelConfig 字段

| 字段 | 类型 | 默认值 | 说明 |
|-----|------|--------|------|
| `id` | string | - | 模型 ID（必需） |
| `role` | string | `"chat"` | 角色：`chat`（对话）/ `embed`（嵌入） |
| `level` | string | `"medium"` | 能力等级：`low`/`medium`/`high` |
| `vision` | bool | `false` | 是否支持视觉 |
| `tool` | bool | `true` | 是否支持工具调用 |
| `enabled` | bool | `true` | 是否启用 |

### 示例

```json
{
  "providers": {
    "local-ollama": {
      "type": "ollama",
      "strategy": "round-robin",
      "endpoints": [
        {
          "base_url": "http://localhost:11434",
          "weight": 1,
          "models": [
            { "id": "qwen3:8b", "role": "chat", "level": "medium", "vision": false }
          ]
        }
      ]
    },
    "gpt-backup": {
      "type": "openai",
      "strategy": "priority",
      "endpoints": [
        {
          "base_url": "https://api.openai.com/v1",
          "api_key": "sk-xxx",
          "models": [
            { "id": "gpt-4o", "role": "chat", "level": "high", "vision": true }
          ]
        }
      ]
    }
  }
}
```

---

## agent（智能体配置）

核心智能体行为配置。

### 字段说明

| 字段 | 类型 | 默认值 | 说明 |
|-----|------|--------|------|
| `model` | string | `"local-ollama/qwen3.5:2b"` | 默认模型（格式：`实例名/模型ID`） |
| `workspace` | string | `"~/.mindbot/workspace"` | 工作空间根目录 |
| `system_path_whitelist` | array | `["~/.mindbot"]` | 允许访问的系统目录白名单 |
| `trusted_paths` | array | `[]` | 可信任的目录（Shell 可切换） |
| `restrict_to_workspace` | bool | `true` | 是否限制文件工具在工作空间内 |
| `shell_execution` | object | 见下方 | Shell 执行策略 |
| `max_tokens` | int | `8192` | 最大输出 token 数 |
| `temperature` | float | `0.7` | 温度参数（0.0-2.0） |
| `max_tool_iterations` | int | `20` | 最大工具调用轮数 |
| `max_sessions` | int | `1000` | 最大会话缓存数（LRU 淘汰） |
| `memory_top_k` | int | `5` | 每轮检索记忆条数 |
| `system_prompt` | string | `""` | 系统提示（可被 SYSTEM.md 覆盖） |
| `tool_persistence` | string | `"none"` | 工具消息持久化：`none`/`summary`/`full` |
| `approval` | object | 见下方 | 工具审批配置 |

### shell_execution 字段

| 字段 | 类型 | 默认值 | 说明 |
|-----|------|--------|------|
| `policy` | string | `"cwd_guard"` | 执行边界：`cwd_guard`（目录校验）/ `sandboxed` |
| `sandbox_provider` | string | `"none"` | 沙箱后端（预留）：`none`/`bubblewrap` |
| `fail_if_unavailable` | bool | `false` | 沙箱不可用时是否失败 |

### approval 字段

| 字段 | 类型 | 默认值 | 说明 |
|-----|------|--------|------|
| `security` | string | `"allowlist"` | 安全级别：`deny`/`allowlist`/`full` |
| `ask` | string | `"off"` | 询问审批时机：`off`/`on_miss`/`always` |
| `timeout` | int | `300` | 审批超时秒数（1-3600） |
| `whitelist` | object | `{}` | 工具白名单（工具名→参数正则列表） |
| `dangerous_tools` | array | `["delete_file", "rm", "shell", ...]` | 危险工具列表 |

### 示例

```json
{
  "agent": {
    "model": "local-ollama/qwen3:8b",
    "workspace": "~/.mindbot/workspace",
    "temperature": 0.7,
    "max_tokens": 8192,
    "memory_top_k": 5,
    "approval": {
      "security": "allowlist",
      "ask": "off",
      "timeout": 300
    }
  }
}
```

---

## routing（路由配置）

根据用户输入自动选择模型等级。

### 字段说明

| 字段 | 类型 | 默认值 | 说明 |
|-----|------|--------|------|
| `auto` | bool | `false` | 是否启用自动路由 |
| `rules` | array | `[]` | 路由规则列表 |

### RoutingRule 字段

| 字段 | 类型 | 默认值 | 说明 |
|-----|------|--------|------|
| `keywords` | array | `[]` | 匹配关键词 |
| `min_length` | int | - | 最小输入长度 |
| `max_length` | int | - | 最大输入长度 |
| `level` | string | `"medium"` | 目标模型等级 |
| `priority` | int | `0` | 规则优先级（越高优先） |

### 示例

```json
{
  "routing": {
    "auto": true,
    "rules": [
      {
        "keywords": ["代码", "编程", "算法"],
        "level": "high",
        "priority": 10
      },
      {
        "keywords": ["你好", "简单"],
        "level": "low",
        "priority": 5
      }
    ]
  }
}
```

---

## memory（记忆配置）

记忆系统配置。

### 字段说明

| 字段 | 类型 | 默认值 | 说明 |
|-----|------|--------|------|
| `storage_path` | string | `"~/.mindbot/data/memory.db"` | SQLite 数据库路径 |
| `markdown_path` | string | `"~/.mindbot/data/memory"` | Markdown 源文件目录 |
| `short_term_retention_days` | int | `7` | 短期记忆保留天数（≥1） |
| `enable_fts` | bool | `true` | 是否启用全文搜索（FTS5） |

### 示例

```json
{
  "memory": {
    "storage_path": "~/.mindbot/data/memory.db",
    "markdown_path": "~/.mindbot/data/memory",
    "short_term_retention_days": 7,
    "enable_fts": true
  }
}
```

---

## skills（技能配置）

Prompt 层技能发现和注入配置。

### 字段说明

| 字段 | 类型 | 默认值 | 说明 |
|-----|------|--------|------|
| `enabled` | bool | `true` | 是否启用技能系统 |
| `skill_dirs` | array | `[]` | 额外技能目录 |
| `always_include` | array | `[]` | 始终加载的技能名 |
| `max_visible` | int | `8` | 最大可见技能数 |
| `max_detail_load` | int | `2` | 最大详情加载技能数 |
| `trigger_mode` | string | `"metadata-match"` | 触发模式：`metadata-match`/`explicit-only`/`hybrid` |

### trigger_mode 说明

| 模式 | 说明 |
|-----|------|
| `metadata-match` | 根据技能 metadata 自动匹配触发 |
| `explicit-only` | 只有用户明确调用才加载 |
| `hybrid` | 混合模式：自动匹配 + 允许显式调用 |

### 示例

```json
{
  "skills": {
    "enabled": true,
    "always_include": ["mindbot-self-knowledge"],
    "max_visible": 8,
    "trigger_mode": "metadata-match"
  }
}
```

---

## context（上下文配置）

上下文窗口管理配置。

### 字段说明

| 字段 | 类型 | 默认值 | 说明 |
|-----|------|--------|------|
| `max_tokens` | int | `8000` | 上下文总 token 预算（≥1） |
| `compression` | string | `"truncate"` | 压缩策略：`truncate`/`summarize`/`extract`/`mix`/`archive` |
| `blocks` | object | 见下方 | 各 block token 预算 |
| `compression_config` | object | 见下方 | 压缩策略参数 |

### blocks 默认比例

| Block | 默认比例 | 计算值（8000 tokens） |
|-------|---------|---------------------|
| `system_identity` | 12% | 960 |
| `skills_overview` | 8% | 640 |
| `skills_detail` | 15% | 1200 |
| `memory` | 15% | 1200 |
| `conversation` | 35% | 2800 |
| `intent_state` | 5% | 400 |
| `user_input` | 10% | 800 |

### compression_config 字段

| 字段 | 类型 | 默认值 | 说明 |
|-----|------|--------|------|
| `recent_keep` | int | `4` | 压缩时保留最近消息数（≥1） |
| `extract_threshold` | int | `2` | 提取策略阈值（≥0） |

### 示例

```json
{
  "context": {
    "max_tokens": 8000,
    "compression": "truncate",
    "blocks": {
      "skills_overview": 640,
      "skills_detail": 1200
    }
  }
}
```

---

## session_journal（会话日志）

会话历史持久化配置。

### 字段说明

| 字段 | 类型 | 默认值 | 说明 |
|-----|------|--------|------|
| `enabled` | bool | `false` | 是否启用会话日志 |
| `path` | string | `"~/.mindbot/data/journal"` | JSONL 文件目录 |

### 示例

```json
{
  "session_journal": {
    "enabled": true,
    "path": "~/.mindbot/data/journal"
  }
}
```

---

## multimodal（多模态配置）

视觉/多模态能力配置。

### 字段说明

| 字段 | 类型 | 默认值 | 说明 |
|-----|------|--------|------|
| `max_images` | int | `10` | 单次最大图片数（≥1） |
| `max_file_size_mb` | float | `20.0` | 最大文件大小 MB（>0） |

### 示例

```json
{
  "multimodal": {
    "max_images": 10,
    "max_file_size_mb": 20.0
  }
}
```

---

## channels（渠道配置）

外部接入渠道配置。

### HTTP 渠道

| 字段 | 类型 | 默认值 | 说明 |
|-----|------|--------|------|
| `enabled` | bool | `false` | 是否启用 |
| `host` | string | `"0.0.0.0"` | 监听地址 |
| `port` | int | `31211` | 监听端口 |

### CLI 渠道

| 字段 | 类型 | 默认值 | 说明 |
|-----|------|--------|------|
| `enabled` | bool | `false` | 是否启用 |

### Feishu 渠道

| 字段 | 类型 | 默认值 | 说明 |
|-----|------|--------|------|
| `enabled` | bool | `false` | 是否启用 |
| `app_id` | string | `""` | 应用 ID |
| `app_secret` | string | `""` | 应用密钥 |
| `encrypt_key` | string | `""` | 加密密钥 |
| `verification_token` | string | `""` | 验证 Token |

### Telegram 渠道（预留）

| 字段 | 类型 | 默认值 | 说明 |
|-----|------|--------|------|
| `enabled` | bool | `false` | 是否启用 |
| `token` | string | `""` | Bot Token |

### 示例

```json
{
  "channels": {
    "http": {
      "enabled": true,
      "port": 31211
    },
    "feishu": {
      "enabled": true,
      "app_id": "cli_xxx",
      "app_secret": "xxx"
    }
  }
}
```

---

## debug（调试配置）

调试选项（预留）。

| 字段 | 类型 | 默认值 | 说明 |
|-----|------|--------|------|
| `dump_prompt_path` | string | `null` | Prompt 导出路径（预留，未使用） |

---

## tool_models（工具模型）

非对话工具模型配置（预留）。

| 字段 | 类型 | 默认值 | 说明 |
|-----|------|--------|------|
| `embed` | string | `null` | 嵌入模型引用（预留） |
| `ocr` | string | `null` | OCR 模型引用（预留） |
| `rerank` | string | `null` | 重排序模型引用（预留） |

---

## 环境变量支持

配置可通过环境变量覆盖，格式：`MIND_<section>__<field>`。

### 示例

```bash
# 设置 agent.temperature
export MIND_AGENT__TEMPERATURE=0.5

# 设置 memory.enable_fts
export MIND_MEMORY__ENABLE_FTS=true

# 设置 agent.model
export MIND_AGENT__MODEL="local-ollama/qwen3:8b"
```

---

## 配置优先级

1. **环境变量** — 最高优先级
2. **settings.json** — 中优先级
3. **Schema 默认值** — 最低优先级

---

## 迁移指南

重新生成配置时，需要迁移的数据：

| 文件/目录 | 说明 | 必需 |
|----------|------|------|
| `data/memory.db` | 记忆数据库 | ✅ |
| `data/memory/long_term/` | 长期记忆源文件 | ✅ |
| `SYSTEM.md` | 系统提示 | ❌ |
| `skills/` | 自定义技能 | ❌ |
| `data/journal/` | 会话历史 | ❌ |

```bash
# 迁移命令
cp ~/.mindbot/data/memory.db /backup/
cp -r ~/.mindbot/data/memory/long_term /backup/
cp ~/.mindbot/SYSTEM.md /backup/
cp -r ~/.mindbot/skills /backup/

# 恢复
cp /backup/memory.db ~/.mindbot/data/
cp -r /backup/long_term ~/.mindbot/data/memory/
```

---

## 常见问题

### Q: 为什么检索不到长期记忆？

A: 确认：
1. `memory.enable_fts` 为 `true`
2. 长期记忆数据已写入数据库
3. 检索关键词与记忆内容匹配

### Q: 如何添加新的模型提供商？

A: 在 `providers` 下添加新实例：

```json
{
  "providers": {
    "my-provider": {
      "type": "openai",
      "endpoints": [{
        "base_url": "https://api.xxx.com/v1",
        "api_key": "xxx",
        "models": [{ "id": "model-xxx", "level": "high" }]
      }]
    }
  }
}
```

### Q: 如何修改系统角色？

A: 编辑 `~/.mindbot/SYSTEM.md` 文件，内容会自动加载为系统提示。

---

## 完整配置示例

```json
{
  "providers": {
    "local-ollama": {
      "type": "ollama",
      "strategy": "round-robin",
      "endpoints": [
        {
          "base_url": "http://localhost:11434",
          "weight": 1,
          "models": [
            { "id": "qwen3:8b", "role": "chat", "level": "medium", "vision": false }
          ]
        }
      ]
    }
  },
  "agent": {
    "model": "local-ollama/qwen3:8b",
    "workspace": "~/.mindbot/workspace",
    "system_path_whitelist": ["~/.mindbot"],
    "restrict_to_workspace": true,
    "shell_execution": {
      "policy": "cwd_guard",
      "sandbox_provider": "none"
    },
    "temperature": 0.7,
    "max_tokens": 8192,
    "max_tool_iterations": 20,
    "max_sessions": 1000,
    "memory_top_k": 5,
    "tool_persistence": "none",
    "approval": {
      "security": "allowlist",
      "ask": "off",
      "timeout": 300
    }
  },
  "routing": {
    "auto": true,
    "rules": [
      { "keywords": ["代码", "编程"], "level": "high", "priority": 10 }
    ]
  },
  "memory": {
    "storage_path": "~/.mindbot/data/memory.db",
    "markdown_path": "~/.mindbot/data/memory",
    "short_term_retention_days": 7,
    "enable_fts": true
  },
  "skills": {
    "enabled": true,
    "always_include": ["mindbot-self-knowledge"],
    "max_visible": 8,
    "trigger_mode": "metadata-match"
  },
  "context": {
    "max_tokens": 8000,
    "compression": "truncate",
    "blocks": {
      "skills_overview": 640,
      "skills_detail": 1200
    }
  },
  "session_journal": {
    "enabled": true,
    "path": "~/.mindbot/data/journal"
  },
  "multimodal": {
    "max_images": 10,
    "max_file_size_mb": 20.0
  },
  "channels": {
    "http": { "enabled": false, "port": 31211 },
    "cli": { "enabled": false },
    "feishu": { "enabled": false }
  }
}
```

---

*文档版本: 2026-04-18*
*适用版本: MindBot 0.3.x*