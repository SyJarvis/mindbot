---
title: MindBot 主入口
---

# MindBot 主入口

`MindBot` 是框架的最高层入口，封装了配置加载、Agent 创建、内存管理和定时任务。大多数用户只需与此类交互。

**模块路径**：`mindbot.bot`

**导入方式**：

```python
from mindbot import MindBot
```

---

## 构造函数

```python
MindBot(
    config: Config | None = None,
    *,
    config_store: ConfigStore | None = None,
) -> None
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `config` | `Config \| None` | `None` | 配置实例。为 `None` 时从 `~/.mindbot/settings.json` 加载，并注入 `~/.mindbot/SYSTEM.md` 中的系统提示 |
| `config_store` | `ConfigStore \| None` | `None` | 可选的预构建 ConfigStore，用于支持热重载 |

!!! note "配置加载顺序"
    1. 若提供 `config_store`，则使用其中的配置并启用热重载。
    2. 若提供 `config`，则直接使用该配置。
    3. 否则从 `~/.mindbot/settings.json` 加载默认配置。若文件不存在则退出并提示运行 `mindbot generate-config`。

---

## 工厂方法

### `from_config()`

```python
@classmethod
MindBot.from_config(config: Config) -> MindBot
```

从 `Config` 实例创建 `MindBot`。

### `from_file()`

```python
@classmethod
MindBot.from_file(path: str | None = None) -> MindBot
```

从配置文件创建 `MindBot`。`path` 为 `None` 时从环境变量构建默认配置。

---

## 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `config` | `Config` | 当前运行时配置 |
| `store` | `ConfigStore \| None` | ConfigStore（仅在热重载模式下可用） |
| `model` | `str` | 当前模型标识，格式为 `instance/model` |
| `provider` | `str` | 当前 Provider 实例名 |
| `greeting` | `str` | 默认问候语 |
| `cron` | `CronService` | 定时任务服务 |
| `is_running` | `bool` | Bot 是否处于运行状态 |

---

## 对话接口

### `chat()`

```python
async def chat(
    message: str,
    session_id: str = "default",
    tools: list[Any] | None = None,
    on_event: Callable[[AgentEvent], None] | None = None,
) -> AgentResponse
```

主要异步对话入口，支持工具调用和实时事件回调。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `message` | `str` | - | 用户消息文本 |
| `session_id` | `str` | `"default"` | 会话标识符，用于维护对话上下文 |
| `tools` | `list[Any] \| None` | `None` | 当次轮次的工具列表。提供时完全覆盖已注册的工具；为 `None` 时使用注册表中的工具 |
| `on_event` | `Callable[[AgentEvent], None] \| None` | `None` | 可选的事件回调，在每个 `AgentEvent` 发出时被调用（如工具调用、流式增量、完成等） |

**返回**：[`AgentResponse`](models.md#agentresponse)

**示例**：

```python
from mindbot import MindBot

bot = MindBot()

# 简单对话
response = await bot.chat("你好！")
print(response.content)

# 带会话 ID 的多轮对话
response1 = await bot.chat("请记住我的名字是小明", session_id="user-1")
response2 = await bot.chat("我叫什么名字？", session_id="user-1")
print(response2.content)  # 应能回忆"小明"

# 带事件回调
def on_event(event):
    print(f"事件: {event.type.value}")

response = await bot.chat("分析这段代码", on_event=on_event)
```

### `chat_stream()`

```python
async def chat_stream(
    message: str,
    session_id: str = "default",
    tools: list[Any] | None = None,
) -> AsyncIterator[str]
```

流式对话入口，逐 Token 输出响应。当没有活跃工具时逐块输出；有工具时先完成整轮再输出最终内容。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `message` | `str` | - | 用户消息文本 |
| `session_id` | `str` | `"default"` | 会话标识符 |
| `tools` | `list[Any] \| None` | `None` | 当次轮次的工具列表 |

**返回**：`AsyncIterator[str]`

**示例**：

```python
bot = MindBot()

async for chunk in bot.chat_stream("讲一个故事"):
    print(chunk, end="", flush=True)
```

---

## 模型切换

### `list_available_models()`

```python
def list_available_models(self) -> list[str]
```

返回所有可用模型列表，格式为 `instance/model`。若启用了路由，则委托路由器返回；否则返回单个配置模型。

### `set_model()`

```python
def set_model(self, model_ref: str) -> None
```

运行时切换活跃模型。

| 参数 | 类型 | 说明 |
|------|------|------|
| `model_ref` | `str` | 模型引用，格式为 `instance/model`，如 `"my-ollama/qwen3"` |

**异常**：若 `instance` 未配置则抛出 `ValueError`。

---

## 内存接口

### `add_to_memory()`

```python
def add_to_memory(self, content: str, permanent: bool = False) -> None
```

向内存中添加内容。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `content` | `str` | - | 要添加的内容 |
| `permanent` | `bool` | `False` | 是否持久化为长期记忆 |

### `search_memory()`

```python
def search_memory(self, query: str, top_k: int = 5) -> list[Any]
```

搜索内存。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `query` | `str` | - | 搜索查询 |
| `top_k` | `int` | `5` | 返回的最大结果数 |

---

## 工具接口

### `register_tool()`

```python
def register_tool(self, tool: Any) -> None
```

注册工具到主 Agent。`tool` 可以是任何具有 `name`、`description`、`parameters`（或 `parameters_json_schema`）和可调用的 `handler`/`run`/`execute` 方法的对象。

### `list_tools()`

```python
def list_tools(self) -> list[Any]
```

返回所有已注册的工具列表。

### `refresh_capabilities()`

```python
def refresh_capabilities(self) -> None
```

刷新运行时可见的能力集。

### `reload_tools()`

```python
async def reload_tools(self) -> int
```

重新加载持久化的工具并刷新能力图。返回加载的工具数量。

---

## 生命周期管理

### `start()`

```python
async def start(self) -> None
```

启动 Bot，包括定时任务服务和配置热重载监听（若可用）。

### `stop()`

```python
async def stop(self) -> None
```

停止 Bot，包括配置热重载监听和定时任务服务。

**示例**：

```python
bot = MindBot()
await bot.start()

try:
    response = await bot.chat("Hello!")
    print(response.content)
finally:
    await bot.stop()
```

---

## 自省

### `get_llm_info()`

```python
def get_llm_info(self) -> ProviderInfo
```

返回当前 LLM 的 Provider 信息，包括 provider 名称、model 名称、是否支持视觉和工具。

---

## 已弃用方法

以下方法保留一个发布周期后将被移除：

| 方法 | 替代方案 |
|------|----------|
| `chat_async()` | 使用 `chat()` |
| `chat_stream_async()` | 使用 `chat_stream()` |
| `chat_with_agent_async()` | 使用 `chat()` 的 `tools=` 参数 |
