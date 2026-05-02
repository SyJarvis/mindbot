# MindBot 定时任务（Cron Tool）实现文档

## 概述

MindBot 已有完整的 `CronService` 后端实现（`src/mindbot/cron/`），支持 `at`/`every`/`cron` 三种调度类型，但缺少用户侧接口。本次实现将 CronService 的能力通过 Tool 系统暴露给 agent，使得用户可以通过自然语言对话创建和管理定时任务。

## 变更文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/mindbot/tools/cron_ops.py` | 新建 | Cron 工具集，6 个 agent 可调用工具 |
| `src/mindbot/bot.py` | 修改 | 接入 on_job 回调 + 注册 cron 工具 + 投递回调 |
| `src/mindbot/tools/__init__.py` | 修改 | 导出 `create_cron_tools` |

## 架构设计

```
用户（CLI / HTTP / 飞书）
  │
  │ "帮我创建每天9点的定时任务"
  ▼
MindBot.chat()
  │
  ▼
MindAgent → ToolRegistry → cron_add tool
  │                              │
  │                              ▼
  │                        CronService.add_job()
  │                              │
  │                              ▼
  │                     ~/.mindbot/cron/jobs.json
  │
  │  ──── 定时触发 ────
  │
  ▼
CronService._tick() → run_job() → on_job callback
                                      │
                                      ▼
                              MindBot._on_cron_job()
                                      │
                                      ▼
                              MindAgent.chat(message)
                                      │
                                      ▼
                              (可选) deliver → Channel → 飞书/HTTP
```

## 工具列表

### 1. cron_add — 创建定时任务

创建一个新的定时任务，支持三种调度类型。

**参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| name | string | 是 | 任务名称 |
| schedule_kind | string | 是 | 调度类型：`at`、`every`、`cron` |
| schedule_value | string | 是 | 调度定义（见下方说明） |
| message | string | 是 | 任务触发时 agent 处理的消息 |
| deliver | boolean | 否 | 是否将响应投递到渠道 |
| channel | string | 否 | 目标渠道（如 `feishu`、`http`） |
| to | string | 否 | 目标用户/聊天 ID |

**schedule_kind 说明：**

- `at` — 一次性执行。`schedule_value` 为 ISO 8601 时间字符串，如 `"2025-06-01T09:00:00"`
- `every` — 固定间隔循环。`schedule_value` 为时长字符串，如 `"5m"`、`"1h"`、`"30s"`、`"2h30m"`
- `cron` — cron 表达式。`schedule_value` 为标准 5 字段表达式，如 `"0 9 * * *"`（每天 9:00）

### 2. cron_list — 列出定时任务

| 参数 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| include_disabled | boolean | 否 | 是否包含已禁用的任务（默认 false） |

### 3. cron_remove — 删除定时任务

| 参数 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| job_id | string | 是 | 任务唯一 ID |

### 4. cron_toggle — 启用/禁用任务

| 参数 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| job_id | string | 是 | 任务唯一 ID |
| enabled | boolean | 否 | 启用或禁用（默认 true） |

### 5. cron_run — 手动触发任务

立即执行一次指定任务（不受启用/禁用状态限制）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| job_id | string | 是 | 任务唯一 ID |

### 6. cron_status — 服务状态

查询 cron 服务的运行状态（任务总数、启用数、是否运行中）。无需参数。

## 核心实现

### cron_ops.py — 工具工厂

遵循 MindBot 现有的工具模式（工厂函数 + closure 捕获服务实例）：

```python
def create_cron_tools(cron_service: CronService) -> list[Tool]:
    async def cron_add(...) -> str:
        # 解析 schedule_kind + schedule_value → CronSchedule
        # 调用 cron_service.add_job()
        ...
    return [Tool(name="cron_add", ..., handler=cron_add), ...]
```

辅助函数：
- `_parse_duration(value: str) -> int` — 解析人类友好的时长字符串为毫秒，支持 `30s`/`5m`/`1h`/`2h30m`/`1d`
- `_job_to_dict(job) -> dict` — 将 CronJob 序列化为 JSON 友好的字典（时间戳转 ISO 8601）

### bot.py — 接入层

三处改动：

1. **on_job 回调**：初始化 `CronService` 时传入 `on_job=self._on_cron_job`
2. **`_on_cron_job()`**：定时任务触发时调用 `agent.chat()` 处理消息，可选投递到渠道
3. **`_register_cron_tools()`**：在 `__init__` 末尾将 6 个工具注册到 agent

### serve.py — 渠道投递（已有）

`serve.py` 中已通过 `bot.set_delivery_callback()` 接入 MessageBus，cron 任务触发后可将 agent 响应投递到飞书、HTTP 等渠道。

## 多渠道支持

所有工具注册在 agent 的 `ToolRegistry` 上，所有渠道共享同一个 agent 实例，因此无需额外适配。

| 渠道 | 创建任务 | 接收触发结果 |
|------|:---:|:---:|
| CLI Shell | 自然语言对话 | 自动返回（交互式） |
| HTTP API | `/chat` 接口 | `deliver=true` 时投递 |
| 飞书 | WebSocket 对话 | `deliver=true` + `channel="feishu"` 时投递 |

## 使用示例

在任意渠道与 MindBot 对话：

```
用户: 帮我创建一个每天早上9点的定时任务，提醒我站起来活动
 → agent 调用 cron_add(schedule_kind="cron", schedule_value="0 9 * * *",
                       message="提醒用户站起来活动一下", name="早晨活动提醒")

用户: 5分钟后提醒我开会
 → agent 调用 cron_add(schedule_kind="at", schedule_value="2025-05-02T15:30:00",
                       message="提醒用户开会", name="开会提醒")

用户: 每30分钟检查一次服务状态
 → agent 调用 cron_add(schedule_kind="every", schedule_value="30m",
                       message="检查服务状态并汇报", name="服务状态检查")

用户: 列出我的所有定时任务
 → agent 调用 cron_list()

用户: 删掉"开会提醒"这个任务
 → agent 调用 cron_list() 找到 job_id → cron_remove(job_id="...")
```

## 数据存储

定时任务持久化在 `~/.mindbot/cron/jobs.json`，格式示例：

```json
{
  "version": 1,
  "jobs": [
    {
      "id": "a1b2c3d4-...",
      "name": "早晨活动提醒",
      "enabled": true,
      "schedule": { "kind": "cron", "expr": "0 9 * * *", "tz": null },
      "payload": { "message": "提醒用户站起来活动一下", "deliver": false },
      "state": { "nextRunAtMs": 1746176400000, "lastStatus": null },
      "deleteAfterRun": false
    }
  ]
}
```
