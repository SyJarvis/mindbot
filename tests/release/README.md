# SDK 真实功能测试

本目录用于验证 MindBot 对外 Python SDK 在真实模型服务下能否正常工作。

这些测试属于发布验收测试：

- 不使用 FakeLLM 或 Mock Provider；
- 不只是检查接口能否启动；
- 会向实际配置的模型发送请求；
- 测试失败时，不应发布新版本。

## 当前测试内容

`test_sdk_functional.py` 当前包含 7 项真实功能测试。

### 1. 非流式对话

通过公开入口调用：

```python
from mindbot import MindBot

response = await bot.chat(...)
```

验证：

- SDK 能向真实 Provider 发起请求；
- 返回内容非空；
- `stop_reason` 为 `completed`；
- 能收到运行时事件；
- 最后一个事件为 `complete`；
- 事件包含 `turn_id`；
- 同一轮事件的 `seq` 连续递增。

### 2. 流式对话

调用 `MindBot.chat_stream()`，验证：

- 能连接真实 Provider 的流式接口；
- 至少返回一个数据块；
- 合并后的响应内容非空。

测试不要求模型复述固定随机字符串，避免模型安全策略或表达差异造成误报。

### 3. 多轮会话上下文

在同一个 `session_id` 中进行两轮真实对话，验证：

- 第二轮能读取第一轮提供的会话信息；
- 会话被写入 Session Journal；
- `list_sessions()` 能返回该会话；
- 会话上下文 Token 数大于零。

### 4. 自定义工具调用

向 `MindBot.chat(..., tools=[...])` 传入测试工具，让真实模型决定并发起工具调用。

验证：

- 模型选择了指定工具；
- 工具参数正确；
- 工具只执行一次；
- 最终响应包含工具返回值；
- 事件流包含 `tool_executing` 和 `tool_result`；
- 最后一个事件为 `complete`。

### 5. 上下文清理

先通过真实对话创建会话上下文，再调用 `clear_context()`，验证清理后的会话
Token 数为零。

### 6. 生命周期

调用 `MindBot.start()` 和 `MindBot.stop()`，验证 `is_running` 状态正确切换。

### 7. SDK 自省

验证：

- `model` 与当前配置一致；
- `provider` 能从模型引用中正确解析；
- `list_available_models()` 返回当前模型；
- `get_llm_info()` 返回正确的 Provider 和模型信息。

## 发布验证器额外检查

推荐通过 `scripts/verify_release.py` 执行完整发布验证。除上述 7 项测试外，
验证器还会检查：

1. wheel 和 sdist 能成功构建；
2. 使用当前 Python 创建干净的临时虚拟环境；
3. 安装 wheel 及其声明的全部依赖；
4. `mindbot --version` CLI 入口可用；
5. 从仓库外导入安装后的 `mindbot`；
6. 确认导入的是 site-packages 中的 wheel，而不是 `src/` 源码；
7. wheel 包含内置 `mindbot/templates/SYSTEM.md`；
8. 安装后的 SDK 能连接真实 Provider 完成对话。

普通回归测试默认跳过。需要同时运行时使用 `--with-regression`。

## 测试隔离

真实功能测试会执行以下隔离：

- 将 `HOME` 替换为 pytest 临时目录；
- 将 workspace、memory、vector 和 journal 路径重定向到临时目录；
- 关闭向量记忆，避免依赖 Embedding 服务；
- 关闭自动路由，确保使用指定模型；
- 关闭工具审批，避免测试等待人工输入；
- 关闭文件日志。

测试不会读写正常的 `~/.mindbot` 运行数据。

## 运行方式

### 使用 `~/.bashrc` 中的配置

若 `.bashrc` 已导出以下变量：

- `MINDBOT_PROVIDER`
- `MINDBOT_PLATFORM`
- `MINDBOT_BASE_URL`
- `MINDBOT_API_KEY`
- `MINDBOT_MODELS`

执行完整发布验证：

```bash
source ~/.bashrc
python scripts/verify_release.py
```

同时运行普通回归测试：

```bash
source ~/.bashrc
python scripts/verify_release.py --with-regression
```

### 使用 MindBot 配置文件

```bash
python scripts/verify_release.py \
  --config /absolute/path/to/settings.json
```

也可以只运行真实 SDK 功能测试：

```bash
MINDBOT_RUN_SDK_FUNCTIONAL=1 \
MINDBOT_SDK_TEST_CONFIG=/absolute/path/to/settings.json \
pytest tests/release -m release -q
```

配置文件中的 `agent.model` 会作为测试模型，测试期间自动关闭路由。

### 直接指定 Provider

```bash
MINDBOT_RUN_SDK_FUNCTIONAL=1 \
MINDBOT_SDK_TEST_PROVIDER=openai \
MINDBOT_SDK_TEST_INSTANCE=release \
MINDBOT_SDK_TEST_MODEL=gpt-4o-mini \
MINDBOT_SDK_TEST_BASE_URL=https://api.openai.com/v1 \
MINDBOT_SDK_TEST_API_KEY="$OPENAI_API_KEY" \
pytest tests/release -m release -q
```

OpenAI-compatible 服务使用 `openai` Provider。Ollama 使用 `ollama` Provider，
并且应选择支持工具调用的模型。

## 尚未测试的功能

以下功能当前不在 SDK 发布测试覆盖范围内：

- Runtime Request 和运行中用户补充输入；
- Permission Request 和人工审批流程；
- Memory 写入、检索、整理和跨进程持久化；
- 向量检索和 Embedding Provider；
- 多模态图片、URL、Base64 和 VLM 对话；
- `MindBot.from_file()`、`from_config()` 和纯环境变量配置组合；
- 运行时 `set_model()` 模型切换；
- 自动路由、Provider 负载均衡、故障转移和健康探测；
- Context 自动压缩和长对话恢复；
- 动态工具创建、持久化和重新加载；
- Skills 加载、选择和脚本执行；
- Cron 创建、执行和渠道投递；
- HTTP、CLI Shell、飞书、ACP 等 Channel；
- 多 Agent 和子 Agent 编排；
- OpenAI-compatible 以外 Provider 的完整兼容性矩阵；
- Python 3.10 至 3.13 的自动 CI 矩阵；
- 性能、并发、超时、限流和长时间稳定性测试。

这些功能需要逐步加入后续发布门禁。在对应真实测试完成前，不能将其视为已通过
SDK 发布验证。
