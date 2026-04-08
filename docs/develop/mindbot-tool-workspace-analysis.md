# MindBot 工具使用策略与 Workspace 机制分析

> 基于 MindBot v0.3.x 源码分析
> 源码位置: `src/mindbot/tools/`

---

## 目录

- [1. 工具体系总览](#1-工具体系总览)
- [2. Workspace 定义与绑定](#2-workspace-定义与绑定)
- [3. 文件工具安全策略](#3-文件工具安全策略)
- [4. Shell 工具安全策略](#4-shell-工具安全策略)
- [5. Web 工具安全策略](#5-web-工具安全策略)
- [6. MindBot 自省工具](#6-mindbot-自省工具)
- [7. 动态工具（create_tool）](#7-动态工具create_tool)
- [8. 工具注册流程](#8-工具注册流程)
- [9. 安全限制层级汇总](#9-安全限制层级汇总)
- [10. 问题分析与改进建议](#10-问题分析与改进建议)

---

## 1. 工具体系总览

MindBot 内置 **4 类工具组**，共 11 个基础工具，外加动态工具能力：

```
MindBot 工具体系
├── 文件工具 (file_ops.py)        ← 受 workspace 沙箱限制
│   ├── read_file                 读取文件（支持 offset/limit 分页）
│   ├── write_file                写入文件（自动创建目录）
│   ├── edit_file                 替换文件中的精确文本
│   ├── list_directory            列出目录内容（支持 glob 过滤）
│   └── file_info                 获取文件/目录基本信息
│
├── Shell 工具 (shell_ops.py)     ← 受 workspace 沙箱限制
│   └── exec_command              执行 shell 命令
│
├── Web 工具 (web_ops.py)         ← 仅 URL 协议校验
│   ├── fetch_url                 获取 URL 内容
│   └── web_search                Brave 搜索（需 API Key）
│
├── MindBot 工具 (mindbot_ops.py) ← 无路径限制
│   └── get_mindbot_runtime_info  返回运行时状态 JSON
│
└── 动态工具 (meta_tool.py)       ← 运行时创建
    └── create_tool               LLM 自助创建新工具
```

### 按安全级别分类

| 安全级别 | 工具 | 限制方式 |
|----------|------|----------|
| **沙箱隔离** | read_file, write_file, edit_file, list_directory, file_info | 路径必须在 workspace 内 |
| **沙箱隔离** | exec_command | working_dir 在 workspace 内 + 危险命令黑名单 |
| **协议限制** | fetch_url, web_search | 仅允许 http/https URL |
| **无限制** | get_mindbot_runtime_info | 可访问任意路径（只读） |
| **动态** | create_tool | 由 LLM 生成，无预定义限制 |

---

## 2. Workspace 定义与绑定

### 2.1 Workspace 来源

Workspace 在 `agent_builder.py` 中**硬编码为 `Path.cwd()`**：

```python
# builders/agent_builder.py (第 112-116 行)
if include_builtin_tools:
    from mindbot.tools import create_builtin_tools
    builtin_tools = create_builtin_tools(Path.cwd())  # ← cwd 即 workspace
```

### 2.2 传递链路

```
create_agent(config)
  │
  ├── create_builtin_tools(workspace=Path.cwd())
  │     │
  │     ├── create_file_tools(root=Path.cwd(), restrict_to_workspace=True)
  │     │     └── _resolve_path() 内部使用 allowed_dir=root
  │     │
  │     ├── create_shell_tools(root=Path.cwd(), restrict_to_workspace=True)
  │     │     └── exec_command() 内部使用 cwd=root
  │     │
  │     ├── create_mindbot_tools(workspace=Path.cwd())  ← 仅用于信息展示
  │     │
  │     └── create_web_tools()  ← 无 workspace 概念
  │
  └── Agent(tools=merged_tools, ...)
```

### 2.3 核心绑定函数

```python
# tools/builtin.py
def create_builtin_tools(
    workspace: Path | None = None,
    *,
    restrict_to_workspace: bool = True,
) -> list[Tool]:
    """创建默认内置工具集。"""
    root = (workspace or Path.cwd()).expanduser().resolve()
    tools: list[Tool] = []
    tools.extend(create_file_tools(root, restrict_to_workspace=restrict_to_workspace))
    tools.extend(create_shell_tools(root, restrict_to_workspace=restrict_to_workspace))
    tools.extend(create_mindbot_tools(root))   # 不受 workspace 限制
    tools.extend(create_web_tools())            # 无 workspace 概念
    return tools
```

### 2.4 运行时示例

从 Journal 中看到的实际值：

```json
{
  "system": {
    "cwd": "/root/research/mindbot",
    "workspace": "/root/research/mindbot"
  }
}
```

即 workspace 被绑定为 `/root/research/mindbot`，所有文件/命令操作都被限制在此目录树内。

---

## 3. 文件工具安全策略

### 3.1 路径沙箱核心函数

所有 5 个文件工具共享同一个路径解析和验证函数 `_resolve_path()`：

```python
# tools/file_ops.py (第 12-19 行)
def _resolve_path(path: str, workspace: Path, allowed_dir: Path | None) -> Path:
    """解析并验证路径是否在允许的工作区内。"""
    target = Path(path).expanduser()              # 展开 ~
    if not target.is_absolute():
        target = workspace / target               # 相对路径 → 基于 workspace
    resolved = target.resolve()                   # 解析符号链接和 ..
    if allowed_dir is not None:
        resolved.relative_to(allowed_dir.resolve())  # ← 超出则抛 ValueError
    return resolved
```

**关键行为**：
- `expanduser()` 展开 `~` 为用户主目录
- 相对路径自动基于 workspace 解析
- `resolve()` 消除 `../` 和符号链接
- `relative_to()` 是安全检查的核心 — 如果路径不在 `allowed_dir` 下，抛出 `ValueError`

### 3.2 沙箱生效条件

```python
# tools/file_ops.py (第 33-41 行)
def create_file_tools(
    workspace: Path | None = None,
    *,
    restrict_to_workspace: bool = True,      # ← 默认开启
) -> list[Tool]:
    root = (workspace or Path.cwd()).expanduser().resolve()
    allowed_dir = root if restrict_to_workspace else None  # ← None = 不限制
```

当 `restrict_to_workspace=True`（默认）时，`allowed_dir` 被设为 workspace 根目录，所有路径操作被限制。

### 3.3 各工具的防护模式

每个文件工具的入口都有相同的 try/except 结构：

```python
# tools/file_ops.py — 以 read_file 为例 (第 42-59 行)
def read_file(path: str, encoding: str = "utf-8", offset: int = 0, limit: int | None = None) -> str:
    try:
        file_path = _resolve_path(path, root, allowed_dir)
    except ValueError:
        return f"Error: path is outside the allowed workspace: {path}"  # ← 拒绝

    if not file_path.exists():
        return f"Error: file not found: {path}"
    if not file_path.is_file():
        return f"Error: not a file: {path}"

    content = file_path.read_text(encoding=encoding)
    return _line_slice(content, offset=offset, limit=limit)
```

**write_file** 额外行为：

```python
# tools/file_ops.py (第 61-76 行)
def write_file(path: str, content: str, encoding: str = "utf-8", create_dirs: bool = True) -> str:
    try:
        file_path = _resolve_path(path, root, allowed_dir)
    except ValueError:
        return f"Error: path is outside the allowed workspace: {path}"

    if create_dirs:
        file_path.parent.mkdir(parents=True, exist_ok=True)  # ← 自动创建父目录

    file_path.write_text(content, encoding=encoding)
    return f"Successfully wrote {len(content)} characters to {file_path}"
```

**edit_file** 额外行为：

```python
# tools/file_ops.py (第 78-117 行)
def edit_file(path: str, old_string: str, new_string: str, encoding: str = "utf-8",
              replace_all: bool = False) -> str:
    try:
        file_path = _resolve_path(path, root, allowed_dir)
    except ValueError:
        return f"Error: path is outside the allowed workspace: {path}"

    # ... 存在性检查 ...

    if not old_string:
        return "Error: old_string must not be empty"
    if old_string == new_string:
        return "Error: old_string and new_string are identical"

    content = file_path.read_text(encoding=encoding)
    count = content.count(old_string)
    if count == 0:
        return f"Error: old_string not found in {path}"
    if count > 1 and not replace_all:      # ← 多处匹配时要求明确 replace_all
        return (
            f"Error: old_string appears {count} times in {path}. "
            "Provide more context or set replace_all=true."
        )

    updated = content.replace(old_string, new_string) if replace_all else content.replace(old_string, new_string, 1)
    file_path.write_text(updated, encoding=encoding)
    return f"Replaced {replaced} occurrence(s) in {file_path}"
```

**list_directory** 额外行为：

```python
# tools/file_ops.py (第 118-143 行)
def list_directory(path: str = ".", pattern: str = "*", include_hidden: bool = False) -> str:
    try:
        dir_path = _resolve_path(path, root, allowed_dir)
    except ValueError:
        return f"Error: path is outside the allowed workspace: {path}"

    # ... 存在性检查 ...

    items: list[str] = []
    for entry in sorted(dir_path.iterdir(), key=lambda item: item.name.lower()):
        if not include_hidden and entry.name.startswith("."):   # ← 默认隐藏 dotfiles
            continue
        if not fnmatch.fnmatch(entry.name, pattern):           # ← glob 过滤
            continue
        prefix = "[DIR]" if entry.is_dir() else "[FILE]"
        items.append(f"{prefix} {entry.name}")
    if not items:
        return f"No entries found matching pattern '{pattern}'"
    return "\n".join(items)
```

### 3.4 拒绝场景示例

来自实际 Journal 日志的拒绝记录：

```
用户请求: list_directory("/root/.mindbot/data")
工具响应: Error: path is outside the allowed workspace: /root/.mindbot/data

原因: workspace = /root/research/mindbot
     /root/.mindbot/data 不在 /root/research/mindbot/ 树内
     → _resolve_path() 中 resolved.relative_to(allowed_dir) 抛出 ValueError
```

---

## 4. Shell 工具安全策略

### 4.1 exec_command 完整防护

Shell 工具有 **4 层防护**：

```python
# tools/shell_ops.py (第 27-120 行)
def create_shell_tools(
    workspace: Path | None = None,
    *,
    restrict_to_workspace: bool = True,
    default_timeout: int = 30,
) -> list[Tool]:
    root = (workspace or Path.cwd()).expanduser().resolve()

    async def exec_command(
        command: str,
        timeout: int = default_timeout,
        working_dir: str | None = None,
        capture_stderr: bool = True,
    ) -> str:
```

**第 1 层：危险命令黑名单**

```python
_DANGEROUS_PATTERNS = [
    r"\brm\s+-[rf]{1,2}\b",   # rm -rf, rm -r, rm -f
    r"\bmkfs\b",              # 格式化文件系统
    r"\bdd\s+if=",            # dd 磁盘写入
    r"\bshutdown\b",          # 关机
    r"\breboot\b",            # 重启
    r">\s*/dev/",             # 重定向到设备文件
]

lowered = command.lower()
for pattern in _DANGEROUS_PATTERNS:
    if re.search(pattern, lowered):
        return "Error: command blocked by safety policy"
```

**第 2 层：工作目录限制**

```python
cwd = root
if working_dir:
    candidate = Path(working_dir).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate          # 相对路径基于 workspace
    try:
        cwd = candidate.resolve()
        if restrict_to_workspace:
            cwd.relative_to(root)             # ← working_dir 超出 workspace 则拒绝
    except ValueError:
        return "Error: working_dir is outside the workspace"
```

**第 3 层：路径穿越检测**

```python
if restrict_to_workspace and ("../" in command or "..\\" in command):
    return "Error: command blocked due to path traversal"
```

**第 4 层：超时 + 输出截断**

```python
# 超时保护
try:
    stdout, stderr = await asyncio.wait_for(
        process.communicate(), timeout=max(timeout, 1)
    )
except asyncio.TimeoutError:
    process.kill()
    await process.wait()
    return f"Error: command timed out after {timeout} seconds"

# 输出截断（10K 字符）
if len(output) > 10_000:
    output = output[:10_000] + "\n... (truncated)"
```

### 4.2 exec_command 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `command` | string | 必填 | 要执行的 shell 命令 |
| `timeout` | int | 30 | 超时秒数 |
| `working_dir` | string | None | 工作目录（必须在 workspace 内） |
| `capture_stderr` | bool | True | 是否捕获 stderr |

---

## 5. Web 工具安全策略

### 5.1 fetch_url

```python
# tools/web_ops.py (第 35-58 行)
async def fetch_url(url: str, timeout: int = 20, max_chars: int = 50_000) -> str:
    # URL 校验
    error = _validate_url(url)
    if error:
        return f"Error: invalid URL: {error}"

    # HTTP 请求
    async with httpx.AsyncClient(timeout=max(timeout, 1), follow_redirects=True) as client:
        response = await client.get(url, headers={"User-Agent": _USER_AGENT})
        response.raise_for_status()

    # HTML → 纯文本
    body = response.text
    content_type = response.headers.get("content-type", "")
    if "html" in content_type:
        body = _strip_html(body)

    # 输出截断（50K 字符）
    if len(body) > max_chars:
        body = body[:max_chars] + "\n... (truncated)"
    return body
```

URL 校验函数：

```python
# tools/web_ops.py (第 23-32 行)
def _validate_url(url: str) -> str | None:
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        return str(exc)
    if parsed.scheme not in {"http", "https"}:  # ← 仅允许 http/https
        return "only http and https URLs are allowed"
    if not parsed.netloc:
        return "URL is missing a host"
    return None
```

### 5.2 web_search

```python
# tools/web_ops.py (第 60-97 行)
async def web_search(query: str, max_results: int = 5) -> str:
    api_key = os.environ.get("BRAVE_API_KEY", "")
    if not api_key:
        # ← 未配置 API Key 时返回明确错误
        return "Error: web_search is unavailable because BRAVE_API_KEY is not configured."

    # Brave Search API 调用
    count = min(max(max_results, 1), 10)  # ← 限制 1-10 条结果
    # ...
```

### 5.3 Web 工具安全特性

| 特性 | 说明 |
|------|------|
| 协议限制 | 仅 http/https |
| 重定向跟随 | 自动跟随（`follow_redirects=True`） |
| HTML 清洗 | 移除 script/style 标签，提取纯文本 |
| 输出截断 | fetch_url: 50K 字符 |
| API Key 检查 | web_search 未配置时明确报错 |
| 结果数量限制 | web_search: 1-10 条 |

---

## 6. MindBot 自省工具

### 6.1 get_mindbot_runtime_info

这个工具**不受 workspace 沙箱限制**，因为它需要访问全局路径来收集运行时信息：

```python
# tools/mindbot_ops.py (第 93-189 行)
def create_mindbot_tools(workspace: Path | None = None) -> list[Tool]:
    root = (workspace or Path.cwd()).expanduser().resolve()

    def get_mindbot_runtime_info() -> str:
        """返回 MindBot 运行时状态 JSON。"""
        home_root = Path.home() / ".mindbot"  # ← 直接访问 ~/.mindbot/

        # 访问全局路径（不受 workspace 限制）
        payload = {
            "config": {
                "mindbot_home": str(home_root),
                "system_prompt_file": _path_info(home_root / "SYSTEM.md"),
                "history_dir": _path_info(home_root / "history"),
                # ...
            },
            "memory": {
                "storage": _path_info(memory_db),       # ~/.mindbot/data/memory.db
                "markdown": _path_info(memory_md),      # ~/.mindbot/data/memory/
            },
            "journal": {
                "path": str(journal_dir),               # ~/.mindbot/data/journal
                # ...
            },
            "system": {
                "workspace": str(root),                 # workspace 信息
                "cwd": str(Path.cwd()),
                # ...
            },
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)
```

**为什么不受限制？** 因为 `_path_info()` 直接使用 `Path.expanduser()` 访问任意路径，不经过 `_resolve_path()` 的沙箱检查。这是设计使然 — 该工具的目的是提供全局运行时视图。

---

## 7. 动态工具（create_tool）

### 7.1 创建流程

动态工具由 `DynamicToolManager` 管理，LLM 可以通过 `create_tool` 元工具在运行时创建新工具：

```python
# builders/agent_builder.py (第 135-157 行)
if enable_dynamic_tools:
    from mindbot.generation.dynamic_manager import DynamicToolManager
    from mindbot.capability.backends.tooling.meta_tool import create_tool_creation_tool

    dynamic_manager = DynamicToolManager(
        llm=llm,
        capability_facade=effective_facade,
        tool_backend=tool_backend,
    )
    create_tool_meta = create_tool_creation_tool(dynamic_manager)
    tool_backend.register_static(create_tool_meta, replace=True)
    merged_tools = _merge_tools(merged_tools, [create_tool_meta])
```

### 7.2 安全考量

动态工具的 handler 由 LLM 生成代码，**不受 workspace 沙箱限制**。这意味着：
- 如果 LLM 生成了访问任意路径的代码，该工具可以突破 workspace 限制
- 动态工具的执行环境与内置工具不同，需要额外的安全审计

---

## 8. 工具注册流程

### 8.1 完整注册链路

```
create_agent(config)
│
├── 1. 内置工具创建
│   ├── create_builtin_tools(Path.cwd())
│   │   ├── create_file_tools(root, restrict_to_workspace=True)
│   │   │   └── [read_file, write_file, edit_file, list_directory, file_info]
│   │   │       每个 handler 通过闭包捕获 root 和 allowed_dir
│   │   │
│   │   ├── create_shell_tools(root, restrict_to_workspace=True)
│   │   │   └── [exec_command]
│   │   │       handler 通过闭包捕获 root 和 restrict_to_workspace
│   │   │
│   │   ├── create_mindbot_tools(root)
│   │   │   └── [get_mindbot_runtime_info]
│   │   │
│   │   └── create_web_tools()
│   │       └── [fetch_url, web_search]
│   │
│   └── 2. 用户自定义工具
│       └── tools 参数传入
│
├── 3. 工具合并（同名覆盖）
│   └── _merge_tools(builtin_tools, user_tools)
│       后注册的同名工具覆盖先注册的
│
├── 4. 动态工具系统
│   ├── ToolBackend(static_registry=ToolRegistry.from_tools(merged_tools))
│   ├── CapabilityFacade() → facade.add_backend(tool_backend)
│   ├── DynamicToolManager(llm, facade, tool_backend)
│   └── create_tool_creation_tool(dynamic_manager)
│       → 注册为 "create_tool" 元工具
│
└── 5. 构造 Agent
    └── Agent(name, llm, tools=merged_tools, capability_facade=facade, ...)
```

### 8.2 闭包机制

文件和 Shell 工具的安全限制通过**闭包捕获**实现：

```python
# tools/file_ops.py — 闭包捕获示例
def create_file_tools(workspace=None, *, restrict_to_workspace=True):
    root = (workspace or Path.cwd()).expanduser().resolve()
    allowed_dir = root if restrict_to_workspace else None
    # ↑ allowed_dir 被闭包捕获，所有内部函数共享

    def read_file(path, ...):
        file_path = _resolve_path(path, root, allowed_dir)  # ← 使用闭包变量
        # ...

    def write_file(path, ...):
        file_path = _resolve_path(path, root, allowed_dir)  # ← 使用闭包变量
        # ...

    # 所有 5 个工具共享同一个 root 和 allowed_dir
    return [Tool(name="read_file", handler=read_file), ...]
```

这意味着：
- 工具一旦创建，workspace 绑定不可更改
- 同一 Agent 内的所有文件工具共享同一个 workspace 边界
- 如果需要不同的 workspace，必须创建新的 Agent 实例

---

## 9. 安全限制层级汇总

### 9.1 完整安全矩阵

| 工具 | 路径沙箱 | 危险命令黑名单 | 路径穿越检测 | 超时保护 | 输出截断 |
|------|:--------:|:------------:|:----------:|:--------:|:--------:|
| read_file | ✅ | - | ✅ (resolve) | - | - |
| write_file | ✅ | - | ✅ (resolve) | - | - |
| edit_file | ✅ | - | ✅ (resolve) | - | - |
| list_directory | ✅ | - | ✅ (resolve) | - | - |
| file_info | ✅ | - | ✅ (resolve) | - | - |
| exec_command | ✅ (working_dir) | ✅ | ✅ | ✅ | ✅ (10K) |
| fetch_url | - | - | - | ✅ | ✅ (50K) |
| web_search | - | - | - | ✅ (10s) | - |
| get_mindbot_runtime_info | ❌ | - | - | - | - |
| create_tool | ❌ | - | - | - | - |

### 9.2 防护机制说明

**路径沙箱**（`_resolve_path`）：
- 展开 `~` 为用户主目录
- 相对路径基于 workspace 解析
- `resolve()` 消除 `../` 和符号链接
- `relative_to()` 检查是否在 workspace 树内
- 超出则返回 `"Error: path is outside the allowed workspace"`

**危险命令黑名单**：
- 正则匹配命令字符串（不区分大小写）
- 覆盖 `rm -rf`、`mkfs`、`dd`、`shutdown`、`reboot`、`> /dev/`
- 匹配到直接返回错误，不执行

**路径穿越检测**：
- Shell 工具额外检查命令中是否包含 `../` 或 `..\`
- 补充 `resolve()` 可能遗漏的场景

**超时保护**：
- Shell 命令：默认 30 秒，可配置
- HTTP 请求：默认 20 秒，可配置
- 超时后 kill 进程/取消请求

**输出截断**：
- Shell 命令：10,000 字符
- HTTP 内容：50,000 字符
- 防止超大输出压垮 LLM 上下文窗口

---

## 10. 问题分析与改进建议

### 10.1 当前问题

**问题 1：Workspace 硬编码为 cwd**

```python
# builders/agent_builder.py
builtin_tools = create_builtin_tools(Path.cwd())  # ← 硬编码
```

无法通过配置文件指定 workspace。部署环境的工作目录可能与期望的项目目录不一致。

**问题 2：MindBot 自身数据目录不可访问**

```
workspace = /root/research/mindbot
用户请求: list_directory("/root/.mindbot/data")
→ Error: path is outside the allowed workspace: /root/.mindbot/data
```

MindBot 自己的数据目录（journal、memory 等）对文件工具不可见，导致 LLM 无法通过正常工具查看自身运行数据。

**问题 3：restrict_to_workspace 全局开关**

所有文件和 Shell 工具共享同一个 `restrict_to_workspace` 开关，无法按工具粒度控制。例如不能设置"read_file 可以读任意路径，但 write_file 限制在 workspace 内"。

**问题 4：动态工具无沙箱**

`create_tool` 生成的工具 handler 不经过 `_resolve_path()`，可以突破 workspace 限制。

### 10.2 改进建议

**建议 1：配置化 Workspace**

在 `Config` 中增加 workspace 配置：

```python
# config/schema.py — 建议新增
class AgentConfig(BaseModel):
    # ... 现有字段 ...
    workspace: str | None = Field(
        default=None,
        description="工作区路径。None = 使用 cwd。",
    )
    restrict_to_workspace: bool = Field(
        default=True,
        description="是否将文件/命令工具限制在工作区内。",
    )
```

**建议 2：安全白名单**

对 MindBot 自身数据目录放行：

```python
# 建议改进 _resolve_path
_ALLOWED_OUTSIDE_PATHS = [
    Path.home() / ".mindbot",     # MindBot 数据目录
]

def _resolve_path(path, workspace, allowed_dir):
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = workspace / target
    resolved = target.resolve()

    if allowed_dir is not None:
        try:
            resolved.relative_to(allowed_dir.resolve())
        except ValueError:
            # 检查白名单
            for allowed in _ALLOWED_OUTSIDE_PATHS:
                try:
                    resolved.relative_to(allowed.resolve())
                    break
                except ValueError:
                    continue
            else:
                raise ValueError(f"Path outside workspace: {path}")
    return resolved
```

**建议 3：分级安全策略**

参考 Claude Code 的 permission mode，增加安全级别：

```python
class ToolSecurityLevel(str, Enum):
    SANDBOX = "sandbox"         # 所有操作限制在 workspace 内
    WHITELIST = "whitelist"     # workspace + 白名单路径
    FULL = "full"               # 无限制（需用户确认）
```

**建议 4：读写分离**

```python
# 建议改进：读操作和写操作使用不同的限制级别
def create_file_tools(workspace, *, read_paths=None, write_restricted=True):
    read_allowed = [workspace] + (read_paths or [])
    write_allowed = [workspace] if write_restricted else None

    def read_file(path, ...):
        file_path = _resolve_path(path, workspace, read_allowed)   # ← 可读多个路径

    def write_file(path, ...):
        file_path = _resolve_path(path, workspace, write_allowed)  # ← 只能写 workspace
```

**建议 5：动态工具沙箱**

为动态工具增加执行隔离：

```python
# 建议改进：动态工具代码审查
class DynamicToolManager:
    def _validate_tool_code(self, code: str) -> bool:
        """检查动态工具代码是否违反安全策略。"""
        forbidden = ["os.system", "subprocess", "eval(", "exec(", "open("]
        return not any(pattern in code for pattern in forbidden)
```

---

*文档生成时间: 2026-04-08*
*分析源码版本: MindBot v0.3.x*
