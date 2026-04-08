# MindBot 配置文档

MindBot 使用 JSON 格式的配置文件，默认路径为 `~/.mindbot/settings.json`。

## 快速开始

运行以下命令生成默认配置文件：

```bash
mindbot generate-config
```

这将创建 `~/.mindbot/settings.json` 文件，包含基础配置。

## 配置文件结构

```json
{
  "providers": {},
  "agent": {},
  "routing": {},
  "memory": {},
  "context": {},
  "session_journal": {},
  "multimodal": {},
  "channels": {}
}
```

## 配置项详解

### providers - 模型提供商配置

配置 AI 模型提供商，支持多实例、多 endpoint 负载均衡。

```json
{
  "providers": {
    "local-ollama": {
      "type": "ollama",
      "strategy": "round-robin",
      "endpoints": [
        {
          "base_url": "http://localhost:11434",
          "api_key": "",
          "weight": 1,
          "models": [
            {
              "id": "qwen3.5:2b",
              "role": "chat",
              "level": "medium",
              "vision": false
            }
          ]
        }
      ]
    }
  }
}
```

字段说明：

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | string | 后端驱动类型：`ollama`、`openai`、`transformers` |
| `strategy` | string | 负载均衡策略：`round-robin`、`random`、`priority` |
| `endpoints` | array | 服务端点列表 |
| `endpoints[].base_url` | string | API 基础 URL |
| `endpoints[].api_key` | string | API 密钥（可选） |
| `endpoints[].weight` | integer | 负载均衡权重，越高请求越多 |
| `endpoints[].models` | array | 该端点可用的模型列表 |
| `models[].id` | string | 模型 ID |
| `models[].role` | string | 模型角色：`chat`、`embed` |
| `models[].level` | string | 模型等级：`low`、`medium`、`high` |
| `models[].vision` | boolean | 是否支持视觉 |

### agent - 代理配置

```json
{
  "agent": {
    "model": "local-ollama/qwen3.5:2b",
    "temperature": 0.7,
    "max_tokens": 8192,
    "max_tool_iterations": 20,
    "approval": {
      "security": "allowlist",
      "ask": "off",
      "timeout": 300
    }
  }
}
```

字段说明：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `model` | string | `local-ollama/qwen3.5:2b` | 默认使用的模型，格式：`实例名/模型ID` |
| `temperature` | float | 0.7 | 采样温度，0-2 之间 |
| `max_tokens` | integer | 8192 | 最大生成 token 数 |
| `max_tool_iterations` | integer | 20 | 最大工具调用迭代次数 |
| `approval.security` | string | `allowlist` | 安全级别：`deny`、`allowlist`、`full` |
| `approval.ask` | string | `off` | 询问模式：`off`、`on_miss`、`always` |
| `approval.timeout` | integer | 300 | 审批超时时间（秒） |

### routing - 动态路由配置

根据用户输入自动选择合适的模型等级。

```json
{
  "routing": {
    "auto": true,
    "rules": [
      {
        "keywords": ["代码", "code", "编程"],
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

字段说明：

| 字段 | 类型 | 说明 |
|------|------|------|
| `auto` | boolean | 是否启用自动路由 |
| `rules` | array | 路由规则列表 |
| `rules[].keywords` | array | 匹配关键词列表 |
| `rules[].level` | string | 目标模型等级 |
| `rules[].priority` | integer | 规则优先级，数字越大越优先 |

### memory - 记忆配置

```json
{
  "memory": {
    "storage_path": "~/.mindbot/data/memory.db",
    "markdown_path": "~/.mindbot/data/memory",
    "short_term_retention_days": 7
  }
}
```

字段说明：

| 字段 | 类型 | 说明 |
|------|------|------|
| `storage_path` | string | 数据库存储路径 |
| `markdown_path` | string | Markdown 记忆文件路径 |
| `short_term_retention_days` | integer | 短期记忆保留天数 |

### context - 上下文配置

```json
{
  "context": {
    "max_tokens": 8000,
    "compression": "truncate"
  }
}
```

字段说明：

| 字段 | 类型 | 说明 |
|------|------|------|
| `max_tokens` | integer | 上下文最大 token 数 |
| `compression` | string | 压缩策略：`truncate`、`summary` |

### session_journal - 会话记录

```json
{
  "session_journal": {
    "enabled": true,
    "path": "~/.mindbot/data/journal"
  }
}
```

字段说明：

| 字段 | 类型 | 说明 |
|------|------|------|
| `enabled` | boolean | 是否启用会话记录 |
| `path` | string | 会话记录存储路径 |

### multimodal - 多模态配置

```json
{
  "multimodal": {
    "max_images": 10,
    "max_file_size_mb": 20
  }
}
```

字段说明：

| 字段 | 类型 | 说明 |
|------|------|------|
| `max_images` | integer | 单请求最大图片数量 |
| `max_file_size_mb` | float | 单文件大小限制（MB） |

### channels - 通道配置

```json
{
  "channels": {
    "http": {
      "enabled": false,
      "host": "0.0.0.0",
      "port": 31211
    },
    "cli": {
      "enabled": false
    },
    "telegram": {
      "enabled": false,
      "token": ""
    },
    "feishu": {
      "enabled": false,
      "app_id": "",
      "app_secret": "",
      "encrypt_key": "",
      "verification_token": ""
    }
  }
}
```

## 环境变量

配置支持环境变量替换，格式为 `{env:VAR_NAME}`：

```json
{
  "providers": {
    "moonshot": {
      "type": "openai",
      "endpoints": [
        {
          "base_url": "https://api.moonshot.cn/v1",
          "api_key": "{env:MOONSHOT_API_KEY}"
        }
      ]
    }
  }
}
```

也可以在配置文件中直接使用环境变量覆盖：

```bash
export MIND_AGENT__TEMPERATURE=0.5
export MIND_AGENT__MODEL=local-ollama/qwen3.5:2b
```

## 多 Provider 配置示例

同时配置本地 Ollama 和 Moonshot API：

```json
{
  "providers": {
    "local-ollama": {
      "type": "ollama",
      "strategy": "round-robin",
      "endpoints": [
        {
          "base_url": "http://localhost:11434",
          "models": [
            { "id": "qwen3.5:2b", "role": "chat", "level": "medium" }
          ]
        }
      ]
    },
    "moonshot": {
      "type": "openai",
      "strategy": "priority",
      "endpoints": [
        {
          "base_url": "https://api.moonshot.cn/v1",
          "api_key": "{env:MOONSHOT_API_KEY}",
          "models": [
            { "id": "kimi-k2.5", "role": "chat", "level": "high", "vision": true }
          ]
        }
      ]
    }
  },
  "agent": {
    "model": "local-ollama/qwen3.5:2b"
  },
  "routing": {
    "auto": true,
    "rules": [
      { "keywords": ["代码", "code"], "level": "high", "priority": 10 }
    ]
  }
}
```

## 配置验证

验证配置文件是否正确：

```bash
mindbot config validate
```

## 查看当前配置

```bash
mindbot config show
```
