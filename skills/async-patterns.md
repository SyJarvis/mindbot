# MindBot 异步编程模式

> 本文件从 AGENTS.md 拆分，提供异步编程规范和 MindBot 专属约束的详细说明。

---

## 核心原则

MindBot 是**全异步系统**，从入口到底层 I/O 均使用 `asyncio`，禁止在主链路引入同步阻塞。

### 规则清单

1. 所有公开接口必须是 `async def`，无同步版本
2. CLI 命令通过 `asyncio.run()` 作为唯一同步入口
3. 禁止在 `async` 函数中使用 `asyncio.run()`（嵌套事件循环）
4. 禁止在 async 函数中调用同步阻塞 I/O（`requests.get`、`open()`、`subprocess.run`）
5. CPU 密集或遗留同步库必须通过 `asyncio.to_thread()` 卸载
6. 禁止在新功能中添加同步 chat 包装

---

## 正确模式

### 资源管理

```python
# OK — async context manager
class AsyncResource:
    async def __aenter__(self): ...
    async def __aexit__(self, *args): ...

async def process_batch(items: list[Item]) -> list[Result]:
    async with AsyncResource() as resource:
        tasks = [resource.process(item) for item in items]
        return await asyncio.gather(*tasks, return_exceptions=True)
```

### 批量处理 + 容错

```python
# OK — gather with return_exceptions
results = await asyncio.gather(
    fetch_url(url1),
    fetch_url(url2),
    return_exceptions=True,
)

for result in results:
    if isinstance(result, Exception):
        logger.error("Task failed: %s", result)
```

### 同步库卸载

```python
# OK — 通过 to_thread 卸载阻塞调用
import json

def _parse_large_json(raw: str) -> dict:
    return json.loads(raw)  # CPU 密集

async def process(raw: str) -> dict:
    return await asyncio.to_thread(_parse_large_json, raw)
```

### 异步上下文管理器

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan():
    resource = await acquire()
    try:
        yield resource
    finally:
        await resource.close()
```

---

## MindBot 专属约束

### MindBot / MindAgent 异步要求

- 所有公开方法均为 `async def`，不提供同步版本
- CLI 命令（typer）通过 `asyncio.run()` 作为唯一同步入口
- 持久化写入通过 `asyncio.to_thread()` 卸载，不阻塞事件循环
- 历史兼容层统一标记 `DeprecationWarning`

```python
# OK
async def chat(self, message: str, ...) -> AgentResponse:
    ...

# FORBIDDEN
def chat(self, message: str, ...) -> AgentResponse:
    ...
```

### StreamingExecutor 异步模式

StreamingExecutor 根据是否有工具选择不同路径：

```python
class StreamingExecutor:
    async def execute_stream(self, messages, on_event=None, tools=None):
        if tools:
            # 有工具 → 非流式（需要完整响应解析 tool_calls）
            return await self._execute_with_tools(messages, on_event, tools)
        # 无工具 → 流式
        return await self._execute_stream_only(messages, on_event)
```

注意：有工具时当前退化为非流式，这是可改进的区域（参见 AGENTS.md "可演进区域"）。

### TurnEngine 异步循环

```python
class TurnEngine:
    async def run(self, messages, on_event=None) -> AgentResponse:
        for iteration in range(self._max_iterations):
            should_continue, messages = await self._execute_iteration(
                messages=messages, iteration=iteration, on_event=on_event,
            )
            if not should_continue:
                break
        ...
```

### PersistenceWriter 异步约束

持久化操作中的文件写入必须卸载：

```python
class PersistenceWriter:
    def commit_turn(self, user_text, response, *, session_id="default"):
        """同步入口（由 Agent._run_turn 调用）"""
        self._commit_conversation(user_text, assistant_text, trace)
        self._commit_memory(user_text, assistant_text)
        # 文件写入在内部使用 asyncio.to_thread
```

---

## 反模式（禁止）

```python
# BAD — 阻塞事件循环
response = requests.get("https://api.example.com")

# BAD — 嵌套事件循环
async def outer():
    result = asyncio.run(inner())  # RuntimeError

# BAD — 文件 I/O 阻塞
with open("big_file.txt") as f:
    data = f.read()

# BAD — CPU 密集阻塞
result = json.loads(huge_json_string)

# BAD — 同步 chat 包装
def chat_sync(self, message):
    return asyncio.run(self.chat(message))
```

---

## 推荐异步库

| 用途 | 同步库（避免） | 异步库（推荐） |
|------|---------------|---------------|
| HTTP 请求 | `requests` | `aiohttp` |
| 文件 I/O | `open()` | `aiofiles` 或 `asyncio.to_thread` |
| 子进程 | `subprocess.run` | `asyncio.create_subprocess_exec` |
| JSON 解析 | `json.loads` (大文件) | `asyncio.to_thread(json.loads)` |
| 数据库 | `sqlite3` | `aiosqlite` |

---

*异步编程模式 | MindBot v0.3.1*
