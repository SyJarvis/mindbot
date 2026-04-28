# Provider 配置

MindBot 支持多种 LLM Provider，统一通过 `providers` 配置项管理。

## 模型格式

模型引用格式为 `instance_name/model_id`，例如：

- `local-ollama/qwen3`
- `moonshot/kimi-k2.5`
- `deepseek/deepseek-chat`

## Ollama（本地）

```jsonc
{
  "providers": {
    "local-ollama": {
      "type": "ollama",
      "endpoints": [{
        "base_url": "http://localhost:11434",
        "models": [
          { "id": "qwen3", "role": "chat", "level": "medium" },
          { "id": "qwen3-vl:8b", "role": "chat", "level": "high", "vision": true }
        ]
      }]
    }
  }
}
```

## OpenAI / 兼容服务

支持 OpenAI、DeepSeek、Moonshot 等兼容 API：

```jsonc
{
  "providers": {
    "openai": {
      "type": "openai",
      "endpoints": [{
        "base_url": "https://api.openai.com/v1",
        "api_key": "{env:OPENAI_API_KEY}",
        "models": [
          { "id": "gpt-4", "role": "chat", "level": "high", "vision": true }
        ]
      }]
    },
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

## 多端点负载均衡

```jsonc
{
  "providers": {
    "moonshot": {
      "type": "openai",
      "strategy": "round-robin",
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

负载均衡策略：

| 策略 | 说明 |
|------|------|
| `round-robin` | 轮询分配请求 |
| `random` | 随机选择端点 |
| `priority` | 按优先级选择，失败时切换 |

## 环境变量替换

配置中使用 `{env:VAR_NAME}` 引用环境变量：

```jsonc
{
  "api_key": "{env:OPENAI_API_KEY}"
}
```

## 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | string | 后端类型：`ollama`、`openai`、`transformers` |
| `strategy` | string | 负载均衡策略 |
| `endpoints` | array | 端点列表 |
| `endpoints[].base_url` | string | API 基础 URL |
| `endpoints[].api_key` | string | API 密钥 |
| `endpoints[].weight` | int | 负载权重 |
| `models[].id` | string | 模型 ID |
| `models[].role` | string | 角色：`chat`、`embed` |
| `models[].level` | string | 等级：`low`、`medium`、`high` |
| `models[].vision` | bool | 是否支持视觉 |

## 故障恢复与健康检查

当某个端点请求失败时，系统会自动标记为 `inactive` 并跳过该端点。**5 分钟内**不会再次尝试该端点，避免重复请求已失效的服务。

后台健康监控（HealthMonitor）每 30 秒探测一次 `inactive` 端点，探测成功后自动恢复为 `active` 状态。

### 自动降级机制

当路由开启（`routing.auto: true`）时，请求会按以下优先级选择模型：

1. **同等级候选**：匹配当前任务等级的模型
2. **降级候选**：同等级全部失败后，自动降级到 `medium` → `low` 等级

例如，一个 `high` 等级的任务会先尝试所有 `level: high` 的模型，全部失败后会继续尝试 `level: medium` 和 `level: low` 的模型。
