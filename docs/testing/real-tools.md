---
title: Real Tools Benchmark
---

# Real Tools Benchmark

`real-tools` 是 MindBot 面向真实环境执行的 benchmark，用来评估 agent 在隔离工作区里调用文件、Shell 和本地 HTTP 工具时，能否真的把任务做成。

和 `ToolCall-15` 不同，它不会 mock 工具结果，而是让 `MindBot.chat()` 真的执行内置工具；但在能力维度上，它对齐了 `ToolCall-15` 的五类框架：

- `tool_selection`
- `parameter_precision`
- `multi_step_chains`
- `restraint_refusal`
- `error_recovery`

## 启动命令

```bash
python benchmark/real-tools/runner.py --config-path ~/.mindbot/settings.json --model gpt-backup/glm-5
```

输出 JSON 报告：

```bash
python benchmark/real-tools/runner.py \
  --config-path ~/.mindbot/settings.json \
  --model gpt-backup/glm-5 \
  --output benchmark/real-tools/reports/latest.json
```

保留失败现场：

```bash
python benchmark/real-tools/runner.py \
  --config-path ~/.mindbot/settings.json \
  --model gpt-backup/glm-5 \
  --keep-artifacts \
  --output benchmark/real-tools/reports/latest.json
```

## 它测什么

- 真实文件读取、写入、精确编辑
- 真实 Shell 命令执行
- 路径越界和危险命令拦截
- 本地 HTTP 获取
- 第一次失败后的恢复能力

## 它怎么评分

每个场景同时看：

- 最终产物是否正确
- `message_trace` 中的工具调用和 `stop_reason` 是否合理

每个场景满分 `2` 分：

- `2`: 输出和轨迹都正确
- `1`: 只有一边正确
- `0`: 两边都不正确

V2 还会输出结构化失败标签，包括：

- `wrong_tool`
- `bad_arguments`
- `missing_step`
- `unsafe_action`
- `recovery_failure`
- `artifact_mismatch`
- `repeated_tool_loop`

命令行和 JSON 报告里都能看到：

- category 汇总
- failure tag 统计
- 每个场景的 `observed_failure_tags`

## 详细说明

完整运行说明、场景列表和结果解释见：

- [benchmark/real-tools/README.md](../../benchmark/real-tools/README.md)
