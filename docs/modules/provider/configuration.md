# Provider 配置指南

本文档介绍如何配置 MindBot 支持的各类 LLM Provider。

## 模型引用格式

MindBot 使用 `instance_name/model_id` 格式引用模型：

```
local-ollama/qwen3
moonshot/kimi-k2.5
deepseek/deepseek-chat
openai/gpt-4o
```

## OpenAI 兼容服务

支持所有兼容 OpenAI API 格式的服务，包括：

- OpenAI 官方 API
- DeepSeek
- Moonshot (Kimi)
- 其他兼容服务

### 基本配置

```jsonc
{
  "providers": {
    "openai": {
      "type": "openai",
      "endpoints": [{
        "base_url": "https://api.openai.com/v1",
        "api_key": "{env:OPENAI_API_KEY}",
        "models": [
          { "id": "gpt-4o", "role": "chat", "level": "high", "vision": true },
          { "id": "gpt-4o-mini", "role": "chat", "level": "medium", "vision": true }
        ]
      }]
    }
  }
}
```

### DeepSeek 示例

```jsonc
{
  "providers": {
    "deepseek": {
      "type": "openai",
      "endpoints": [{
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "{env:DEEPSEEK_API_KEY}",
        "models": [
          { "id": "deepseek-chat", "role": "chat", "level": "high" },
          { "id": "deepseek-reasoner", "role": "chat", "level": "high" }
        ]
      }]
    }
  }
}
```

### Moonshot 示例

```jsonc
{
  "providers": {
    "moonshot": {
      "type": "openai",
      "endpoints": [{
        "base_url": "https://api.moonshot.cn/v1",
        "api_key": "{env:MOONSHOT_API_KEY}",
        "models": [
          { "id": "kimi-k2.5", "role": "chat", "level": "high" }
        ]
      }]
    }
  }
}
```

## Ollama（本地）

Ollama 用于连接本地运行的 Ollama 服务。

### 基本配置

```jsonc
{
  "providers": {
    "local-ollama": {
      "type": "ollama",
      "endpoints": [{
        "base_url": "http://localhost:11434",
        "models": [
          { "id": "qwen3", "role": "chat", "level": "medium" },
          { "id": "qwen3-vl:8b", "role": "chat", "level": "high", "vision": true },
          { "id": "llama3.2-vision", "role": "chat", "level": "high", "vision": true }
        ]
      }]
    }
  }
}
```

### 自动拉取模型

配置 `auto_pull: true` 可在模型不存在时自动拉取：

```jsonc
{
  "providers": {
    "local-ollama": {
      "type": "ollama",
      "endpoints": [{
        "base_url": "http://localhost:11434",
        "models": [{ "id": "qwen3", "role": "chat", "level": "medium" }]
      }],
      "auto_pull": true,
      "pull_method": "api",      // "api", "cli" 或 "auto"
      "pull_timeout": 600,       // 等待超时（秒）
      "pull_background": true    // 后台拉取
    }
  }
}
```

### 多端点配置

```jsonc
{
  "providers": {
    "ollama-cluster": {
      "type": "ollama",
      "strategy": "round-robin",
      "endpoints": [
        {
          "base_url": "http://ollama-1:11434",
          "weight": 2,
          "models": [{ "id": "qwen3", "role": "chat", "level": "medium" }]
        },
        {
          "base_url": "http://ollama-2:11434",
          "weight": 1,
          "models": [{ "id": "qwen3", "role": "chat", "level": "medium" }]
        }
      ]
    }
  }
}
```

## Transformers

Transformers Provider 用于直接使用 HuggingFace Transformers 进行本地推理（**暂未完整实现**）。

```jsonc
{
  "providers": {
    "local-transformers": {
      "type": "transformers",
      "endpoints": [{
        "models": [
          { "id": "microsoft/Phi-3-mini-4k-instruct", "role": "chat", "level": "low" }
        ]
      }]
    }
  }
}
```

## 多端点负载均衡

单个 Provider 可配置多个端点，实现负载均衡和高可用。

### 负载均衡策略

| 策略 | 说明 |
|------|------|
| `round-robin` | 轮询分配请求（默认） |
| `random` | 随机选择端点 |
| `priority` | 按优先级选择，失败时切换 |
| `weighted` | 根据 weight 字段加权分配 |

### 配置示例

```jsonc
{
  "providers": {
    "moonshot": {
      "type": "openai",
      "strategy": "weighted",
      "endpoints": [
        {
          "base_url": "https://api.moonshot.cn/v1",
          "api_key": "{env:MOONSHOT_KEY_1}",
          "weight": 2,
          "models": [{ "id": "kimi-k2.5", "level": "high" }]
        },
        {
          "base_url": "https://api.moonshot.cn/v1",
          "api_key": "{env:MOONSHOT_KEY_2}",
          "weight": 1,
          "models": [{ "id": "kimi-k2.5", "level": "high" }]
        }
      ]
    }
  }
}
```

## 环境变量替换

配置支持使用 `{env:VAR_NAME}` 语法引用环境变量：

```jsonc
{
  "api_key": "{env:OPENAI_API_KEY}",
  "base_url": "{env:CUSTOM_API_URL}"
}
```

如果环境变量未设置，启动时会报错。

## 模型配置字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | 是 | 模型 ID |
| `role` | string | 是 | 角色：`chat` 或 `embed` |
| `level` | string | 是 | 能力等级：`low`、`medium`、`high` |
| `vision` | bool | 否 | 是否支持视觉输入（默认 false） |

## Provider 通用字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `type` | string | 是 | Provider 类型标识 |
| `strategy` | string | 否 | 负载均衡策略 |
| `endpoints` | array | 是 | 端点列表 |
| `endpoints[].base_url` | string | 是 | API 基础 URL |
| `endpoints[].api_key` | string | 否 | API 密钥 |
| `endpoints[].weight` | int | 否 | 负载权重（默认 1） |
| `endpoints[].temperature` | float | 否 | 默认温度参数 |
| `endpoints[].max_tokens` | int | 否 | 默认最大 token 数 |

## 路由配置

在 `agent` 配置中指定默认模型和路由策略：

```jsonc
{
  "agent": {
    "model": "local-ollama/qwen3",
    "routing": {
      "auto": true,           // 启用自动路由
      "enable_fallbacks": true  // 启用失败回退
    }
  }
}
```

详见 [Routing 配置](../configuration/channels-config.md)。

## 完整示例

```jsonc
{
  "providers": {
    "local-ollama": {
      "type": "ollama",
      "endpoints": [{
        "base_url": "http://localhost:11434",
        "models": [
          { "id": "qwen3", "role": "chat", "level": "medium" },
          { "id": "nomic-embed-text", "role": "embed", "level": "medium" }
        ]
      }],
      "auto_pull": true
    },
    "deepseek": {
      "type": "openai",
      "endpoints": [{
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "{env:DEEPSEEK_API_KEY}",
        "models": [
          { "id": "deepseek-chat", "role": "chat", "level": "high" }
        ]
      }]
    }
  },
  "agent": {
    "model": "local-ollama/qwen3",
    "embed_model": "local-ollama/nomic-embed-text",
    "routing": {
      "auto": true,
      "enable_fallbacks": true
    }
  }
}
```
