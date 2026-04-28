# 路由系统 (Routing)

MindBot 路由系统负责自动选择最合适的模型，并在模型失败时自动降级。

## 概述

当 `routing.auto: true` 时，系统使用 `RoutingProviderAdapter` 替代单一 provider，根据任务特征动态选择模型。

```
用户请求 → 规则匹配/复杂度评估 → 选择模型等级 → 尝试候选 → 失败时降级
```

## 模型选择流程

### 1. 媒体规则（最高优先级）

如果消息包含图片，优先选择支持视觉的模型：

```python
if has_images(messages):
    return select_by_capability("vision", ...)
```

### 2. 关键词规则

匹配 `routing.rules` 中的关键词：

```jsonc
{
  "routing": {
    "rules": [
      {
        "keywords": ["代码", "code", "编程"],
        "level": "high",
        "priority": 10
      }
    ]
  }
}
```

规则按 `priority` 降序匹配，首个匹配的关键词规则生效。

### 3. 复杂度评估

无关键词匹配时，自动评估任务复杂度：

| 特征 | 权重 | 说明 |
|------|------|------|
| 文本长度 | 30% | 约 300 词为中等基准 |
| 代码块 | 40% | 检测到 ``` 或 `code` |
| 数学表达式 | 20% | 数字运算、变量赋值 |
| 技术关键词 | 10% | algorithm、数据结构等 |

复杂度等级：
- `score < 0.3` → `low`
- `0.3 <= score < 0.6` → `medium`
- `score >= 0.6` → `high`

## 降级机制

选定等级后，系统构建 fallback 链：

```
同等级候选 → medium 候选 → low 候选
```

例如，`high` 等级的任务：

1. 先尝试所有 `level: high` 的模型
2. 全部失败后，尝试 `level: medium` 的模型
3. 仍然失败，尝试 `level: low` 的模型

## 健康检查

### 端点状态

| 状态 | 说明 |
|------|------|
| `active` | 健康，可正常使用 |
| `inactive` | 请求失败，进入冷却期 |
| `probing` | 正在后台探测中 |

### 冷却期 (Cooldown)

端点失败后进入 **5 分钟冷却期**，期间请求跳过该端点。

```python
def should_try():
    if is_healthy:
        return True
    return time_since_failure > 300  # 5分钟
```

### 后台探测

`HealthMonitor` 每 30 秒探测一次 `inactive` 端点：

- 探测成功 → 恢复 `active` 状态
- 探测失败 → 保持 `inactive`，下次继续探测

## 配置示例

```jsonc
{
  "providers": {
    "moonshot": {
      "type": "openai",
      "endpoints": [{
        "base_url": "https://api.moonshot.cn/v1",
        "api_key": "...",
        "models": [
          { "id": "kimi-k2.5", "level": "high", "vision": true }
        ]
      }]
    },
    "ollama": {
      "type": "ollama",
      "endpoints": [{
        "base_url": "http://localhost:11434",
        "models": [
          { "id": "qwen3.5:2b", "level": "medium" }
        ]
      }]
    },
    "hailo": {
      "type": "hailo",
      "endpoints": [{
        "base_url": "local",
        "models": [
          { "id": "qwen3:1.7b", "level": "low" }
        ]
      }]
    }
  },
  "routing": {
    "auto": true,
    "rules": [
      { "keywords": ["代码", "code"], "level": "high", "priority": 10 },
      { "keywords": ["你好", "hello"], "level": "low", "priority": 5 }
    ]
  }
}
```

## 日志解读

```
[15:51:56] Routing decision: level=high, rule=keyword:['代码']
[15:51:56] Model gpt-backup/0/glm-5 failed: 401 invalid_api_key
[15:51:56] Model gpt-backup/1/kimi-k2.5 failed: 404 resource_not_found
[15:51:56] Model local-ollama/0/qwen3.5:2b succeeded
```

- 第一行：路由决策（high 等级，触发了关键词规则）
- 第 2-3 行：high 等级模型失败，自动降级
- 第 4 行：medium 等级模型成功

## 关键文件

- `src/mindbot/routing/router.py` - 路由决策、复杂度评分
- `src/mindbot/routing/adapter.py` - ProviderAdapter 包装、fallback 执行
- `src/mindbot/routing/endpoint.py` - 端点健康状态管理
- `src/mindbot/routing/health.py` - 后台健康监控
