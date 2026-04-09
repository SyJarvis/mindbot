# MindBot Real Tools Benchmark

`benchmark/real-tools` 是 MindBot 的真实环境 agent benchmark。

它保留 `ToolCall-15` 的五类能力框架，但不 mock 工具结果，而是直接通过 `MindBot.chat()` 在隔离工作区里执行真实文件、Shell 和本地 HTTP 工具。

## V2 目标

`real-tools` V2 想回答四个问题：

- agent 是否真的能在真实环境里完成任务
- 失败到底是选错工具、参数错误、步骤缺失、危险操作，还是恢复失败
- 五类能力维度是否均衡
- 它与 `ToolCall-15` 的差距主要在 `tool calling` 还是真实执行

## 与 ToolCall-15 的关系

- `ToolCall-15`：测 OpenAI-compatible `tool_calls` 输出质量，工具执行是 deterministic mock
- `real-tools`：测 MindBot 在真实 workspace 里的执行质量，工具调用会真的读写文件、跑 shell、访问本地 HTTP

两者最好配合看：

- `ToolCall-15` 更适合比较“模型会不会正确调用工具”
- `real-tools` 更适合比较“agent 在真实环境里能不能把事情做成”

## 评测范围

当前 benchmark 覆盖：

- 文件工具：`read_file`、`write_file`、`edit_file`、`list_directory`、`file_info`
- Shell 工具：`exec_command`
- 本地 HTTP 工具：`fetch_url`

当前不覆盖：

- `web_search`
- browser / GUI / desktop automation
- 动态工具生成

## 五类能力维度

V2 按 `ToolCall-15` 风格分成 5 类：

- `tool_selection`
- `parameter_precision`
- `multi_step_chains`
- `restraint_refusal`
- `error_recovery`

当前内置 13 个 deterministic 场景，其中恢复类新增了 4 个：

- `rt10_missing_path_recovery`
- `rt11_ambiguous_edit_recovery`
- `rt12_shell_command_recovery`
- `rt13_fetch_recovery`

## 场景设计约定

每个场景定义都带有：

- `category`
- `success_case`
- `failure_case`
- 可选的 `failure_tags`

所有 `output_checks.path` 统一约定为相对于“当前场景 workspace 根目录”的相对路径。V2 仍兼容旧格式中重复携带场景 ID 前缀的路径，方便老报告和旧测试平滑迁移。

## 运行方式

### 1. 准备配置

确保已经有可用的 MindBot 配置：

```bash
mindbot generate-config
mindbot config validate
```

如果要固定模型，建议在 benchmark 时显式传 `--model`。

### 2. 运行 benchmark

在仓库根目录执行：

```bash
python benchmark/real-tools/runner.py \
  --config-path ~/.mindbot/settings.json \
  --model gpt-backup/glm-5
```

### 3. 输出 JSON 报告

```bash
python benchmark/real-tools/runner.py \
  --config-path ~/.mindbot/settings.json \
  --model gpt-backup/glm-5 \
  --output benchmark/real-tools/reports/latest.json
```

### 4. 保留失败现场

```bash
python benchmark/real-tools/runner.py \
  --config-path ~/.mindbot/settings.json \
  --model gpt-backup/glm-5 \
  --keep-artifacts \
  --output benchmark/real-tools/reports/latest.json
```

保留下来的内容会放到 `benchmark/real-tools/artifacts/`。

### 5. 只跑指定场景

```bash
python benchmark/real-tools/runner.py \
  --config-path ~/.mindbot/settings.json \
  --model gpt-backup/glm-5 \
  --scenario rt02_precise_edit \
  --scenario rt12_shell_command_recovery
```

## 评分方式

每个场景同时看两类信号：

- 最终产物：文件内容、路径状态、最终回答
- 执行轨迹：`AgentResponse.message_trace` 中的工具调用、参数和 `stop_reason`

每题满分 `2` 分：

- `2`: 输出和轨迹都正确
- `1`: 输出或轨迹只有一边正确
- `0`: 输出和轨迹都不满足

## Failure Tags

V2 会把失败归因为结构化标签，当前包括：

- `wrong_tool`
- `bad_arguments`
- `missing_step`
- `unsafe_action`
- `recovery_failure`
- `artifact_mismatch`
- `repeated_tool_loop`

这些标签不是“唯一真相”，而是一个稳定、可聚合的失败切面，方便观察模型的主要弱点。

## 命令行输出

文本报告现在会显示：

- 总分
- `Balanced Category Score`
- `pass / partial / fail`
- 每类 category 汇总
- 全局 `failure tag` 统计
- 每个场景的工具使用、`stop_reason` 和失败标签

## JSON 报告字段

JSON 报告除了原有字段，还会新增：

- `balanced_score_percent`
- `category_summaries`
- `failure_tag_counts`
- 每个场景的 `category`
- 每个场景的 `expected_failure_tags`
- 每个场景的 `observed_failure_tags`

## 为什么它有价值

这个 benchmark 能回答 `ToolCall-15` 回答不了的问题：

- MindBot 是否真的执行了正确工具
- 最终文件和命令输出是否正确
- 遇到第一次失败时有没有恢复能力
- 失败更像是模型规划问题、参数问题，还是真实执行问题

## 注意事项

- runner 会通过 `MindBot.chat()` 主链路执行，不会直接调用 provider
- runner 只暴露 benchmark 需要的内置工具，避免动态工具干扰
- runner 使用固定 benchmark system prompt，并关闭自动路由、skills 和审批等待，以提高可重复性
- benchmark 默认 `temperature = 0`，并把工作区限制在临时隔离目录中
