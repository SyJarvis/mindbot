---
title: ToolCall-15 Benchmark
---

# ToolCall-15 Benchmark

`ToolCall-15` 是 MindBot 当前阶段的主 benchmark。

它不是最广义的 agent benchmark，但和 MindBot 现阶段的能力形态最匹配：工具选择、参数精度、多步工具链、约束遵循和失败恢复。

## 为什么先选它

- `MindBot` 当前更像通用工具型 agent 框架，而不是 browser agent 或 desktop computer-use agent。
- 内置能力集中在文件、Shell、轻量 Web 工具、Skills、记忆和路由。
- `ToolCall-15` 用固定工具集和确定性评分测 tool use，能稳定建立第一条基线。
- 仓库内已经包含 [benchmark/ToolCall-15](../../benchmark/ToolCall-15/README.md)，接入成本低。

## 当前不优先的 benchmark

以下 benchmark 现在不适合作为第一优先：

- `WebArena` / `VisualWebArena`：需要浏览器自动化和视觉定位。
- `OSWorld`：需要桌面 GUI 和 computer-use 执行环境。
- `WorkArena`：需要企业 Web UI 自动化。

这些 benchmark 更适合作为后续能力扩展后的第二阶段或第三阶段目标。

## 新增的适配器

MindBot 现在提供了一个最小 OpenAI-compatible 适配器命令：

```bash
mindbot toolcall15-adapter --host 127.0.0.1 --port 11435 --model gpt-backup/glm-5
```

这个命令会启动 `/v1/chat/completions` 接口，供 `ToolCall-15` 调用。

说明：

- `ToolCall-15` 自己负责工具循环和 mock 工具执行。
- 适配器负责把 OpenAI-compatible 请求转换成 MindBot 的 provider 调用。
- 为了保证 benchmark 稳定性，建议给 `--model` 传固定的 `instance/model`，不要依赖自动路由。

## Benchmark 启动速查

如果你只想尽快把 benchmark 跑起来，按下面 5 步执行即可。

### 1. 准备 MindBot 配置

确保已经完成：

```bash
pip install -e .
mindbot generate-config
mindbot config validate
```

然后确认 `~/.mindbot/settings.json` 里已经有你要测的模型，例如：

```jsonc
{
  "providers": {
    "local-ollama": {
      "type": "ollama",
      "endpoints": [
        {
          "base_url": "http://localhost:11434",
          "models": [
            { "id": "qwen3", "role": "chat", "level": "medium", "vision": false }
          ]
        }
      ]
    }
  },
  "agent": {
    "model": "local-ollama/qwen3",
    "temperature": 0,
    "max_tokens": 8192
  },
  "routing": {
    "auto": false
  }
}
```

### 2. 启动 ToolCall-15 适配器

```bash
mindbot toolcall15-adapter --host 127.0.0.1 --port 11435 --model local-ollama/qwen3
```

建议单独开一个终端保持它持续运行。

### 3. 自检适配器是否正常

适配器起来后，先用 `curl` 检查：

```bash
curl http://127.0.0.1:11435/health
curl http://127.0.0.1:11435/v1/models
```

如果都正常，再做一次最小聊天请求：

```bash
curl http://127.0.0.1:11435/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "local-ollama/qwen3",
    "messages": [
      {"role": "system", "content": "You are a helpful assistant."},
      {"role": "user", "content": "Reply with exactly: ok"}
    ]
  }'
```

如果返回 OpenAI-compatible JSON，就说明适配器链路通了。

### 4. 配置 ToolCall-15

进入 `benchmark/ToolCall-15`，复制环境变量模板：

```bash
cd benchmark/ToolCall-15
cp .env.example .env
```

然后在 `.env` 里写：

```env
LMSTUDIO_HOST=http://127.0.0.1:11435
LLM_MODELS=lmstudio:local-ollama/qwen3
MODEL_REQUEST_TIMEOUT_SECONDS=30
```

这里复用的是 `ToolCall-15` 现有的 OpenAI-compatible host 配置逻辑，真正响应请求的是 MindBot 适配器。

### 5. 启动 ToolCall-15 UI

```bash
cd benchmark/ToolCall-15
npm install
npm run dev
```

然后打开：

- `http://localhost:3000`

点击运行按钮后，`ToolCall-15` 就会通过 MindBot 适配器对指定模型发起 benchmark。

## 完整推荐跑法

### 1. 配置 MindBot

先确保 `~/.mindbot/settings.json` 里已经配置好目标 provider 和模型。

建议：

- 关闭自动路由，或至少在 benchmark 时使用 `--model` 固定模型
- 把目标模型的温度设为 `0`
- 保持 provider、上下文和权限设置固定

### 2. 启动适配器

```bash
mindbot toolcall15-adapter --host 127.0.0.1 --port 11435 --model local-ollama/qwen3
```

### 3. 配置 ToolCall-15

在 `benchmark/ToolCall-15/.env` 里，把适配器当作一个 OpenAI-compatible host 使用。

一个可用示例：

```env
LMSTUDIO_HOST=http://127.0.0.1:11435
LLM_MODELS=lmstudio:local-ollama/qwen3
MODEL_REQUEST_TIMEOUT_SECONDS=30
```

这里使用 `lmstudio` 只是为了复用 `ToolCall-15` 现有的 OpenAI-compatible provider host 逻辑；真正提供响应的是 MindBot 适配器。

### 4. 运行 benchmark

```bash
cd benchmark/ToolCall-15
npm install
npm run dev
```

然后在浏览器打开 `http://localhost:3000`。

## 推荐目录下的实际命令顺序

下面是一套可以直接复制执行的最小流程。

终端 1：

```bash
cd /root/research/mindbot
mindbot toolcall15-adapter --host 127.0.0.1 --port 11435 --model local-ollama/qwen3
```

终端 2：

```bash
cd /root/research/mindbot/benchmark/ToolCall-15
cp .env.example .env
```

然后编辑 `.env`：

```env
LMSTUDIO_HOST=http://127.0.0.1:11435
LLM_MODELS=lmstudio:local-ollama/qwen3
MODEL_REQUEST_TIMEOUT_SECONDS=30
```

继续在终端 2：

```bash
npm install
npm run dev
```

最后在浏览器访问 `http://localhost:3000` 并点击运行。

## 常见问题

### 1. `Config not found`

说明还没有初始化 MindBot 配置。

执行：

```bash
mindbot generate-config
```

### 2. `/health` 正常，但 benchmark 无法运行

通常检查这几项：

- `.env` 里的 `LMSTUDIO_HOST` 是否写成了 `http://127.0.0.1:11435`
- `LLM_MODELS` 里的模型名是否和 `--model` 一致
- 适配器进程是否还在运行

### 3. 模型返回错误或超时

建议先：

- 把目标模型温度固定成 `0`
- 把 `MODEL_REQUEST_TIMEOUT_SECONDS` 保持在 `30` 或更高
- 先只测一个固定模型，不要同时测多个模型

### 4. benchmark 分数波动

首轮基线建议：

- 使用固定模型
- 固定温度
- 固定 provider
- 每轮至少跑 3 次
- 用 [toolcall15-baseline-template.md](toolcall15-baseline-template.md) 记录结果

## 首轮基线建议

首轮只做一个固定基线，不要同时比较太多变量。

推荐固定项：

- 模型：1 个固定 `instance/model`
- 温度：`0`
- 工具格式：默认 OpenAI tool calling
- 请求超时：`30s`
- 每个场景至少跑 `3` 轮，记录均值和最差结果

建议记录指标：

- 总分
- 每个 category 分数
- 15 个场景的 pass / partial / fail
- 平均耗时
- 超时次数
- 失败类型备注

## 记录模板

首轮结果建议按 [toolcall15-baseline-template.md](toolcall15-baseline-template.md) 记录，方便后续横向比较。

## 第二阶段 benchmark 选择

`ToolCall-15` 稳定后，再补一个更接近真实 agent 的 benchmark。

优先顺序：

1. `TAU-bench`
2. `GAIA`

选择建议：

- 如果你更关心多轮工具调用、事务执行、策略可靠性，优先 `TAU-bench`
- 如果你更关心通用 assistant、多步求解和外部信息整合，优先 `GAIA`

## 不要混淆的点

`ToolCall-15` 评的是：

- tool calling 表现
- 工具链决策质量
- 参数与约束遵循

它不直接评：

- 长流程真实浏览器任务
- 桌面 GUI 操作
- 完整 software engineering 修复闭环

所以它是 `MindBot v1 benchmark`，不是最终唯一 benchmark。
