# 通道配置

MindBot 支持多种通信通道：CLI、HTTP、飞书、Telegram。

## HTTP

```jsonc
{
  "channels": {
    "http": {
      "enabled": true,
      "host": "0.0.0.0",
      "port": 31211
    }
  }
}
```

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enabled` | bool | false | 是否启用 |
| `host` | string | `0.0.0.0` | 监听地址 |
| `port` | int | 31211 | 监听端口 |

## 飞书

```jsonc
{
  "channels": {
    "feishu": {
      "enabled": true,
      "app_id": "cli_xxx",
      "app_secret": "xxx",
      "encrypt_key": "xxx",
      "verification_token": "xxx"
    }
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `app_id` | string | 飞书应用 ID |
| `app_secret` | string | 飞书应用密钥 |
| `encrypt_key` | string | 事件加密密钥 |
| `verification_token` | string | 事件验证 Token |

### 飞书附件支持

飞书通道支持原生附件发送：

- `content` 渲染为飞书卡片消息
- `media` 可放本地文件路径列表，通道会先上传再发送原生 `image` 或 `file` 消息

```python
from mindbot.agent.models import AgentResponse
from mindbot.bus import OUTBOUND_MESSAGE_METADATA_KEY

response = AgentResponse(
    content="报告已生成",
    metadata={
        OUTBOUND_MESSAGE_METADATA_KEY: {
            "media": ["/tmp/report.pdf"],
        }
    },
)
```

## Telegram

```jsonc
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "{env:TELEGRAM_BOT_TOKEN}"
    }
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `token` | string | Bot Token，支持环境变量替换 |

## 启动多通道

```bash
mindbot serve
```

`mindbot serve` 会根据配置中 `enabled: true` 的通道自动启动。
