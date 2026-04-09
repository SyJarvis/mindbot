from __future__ import annotations

import json
from pathlib import Path

from mindbot.agent.models import AgentResponse, StopReason
from mindbot.benchmarking.real_tools import (
    BENCHMARK_TOOL_NAMES,
    BenchmarkRunReport,
    benchmark_tools,
    build_benchmark_config,
    evaluate_scenario,
    format_report_text,
    load_scenarios,
)
from mindbot.context.models import Message, ToolCall


def _write_config(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "providers": {
                    "local-ollama": {
                        "type": "ollama",
                        "endpoints": [
                            {
                                "base_url": "http://localhost:11434",
                                "models": [{"id": "qwen3", "role": "chat", "vision": False}],
                            }
                        ],
                    }
                },
                "agent": {
                    "model": "local-ollama/qwen3",
                    "workspace": "~/.mindbot/workspace",
                    "system_path_whitelist": ["~/.mindbot"],
                    "restrict_to_workspace": True,
                    "temperature": 0.7,
                    "max_tokens": 4096,
                    "max_tool_iterations": 20,
                    "tool_persistence": "none",
                },
                "routing": {"auto": True, "rules": []},
                "skills": {"enabled": True},
                "memory": {
                    "storage_path": "~/.mindbot/data/memory.db",
                    "markdown_path": "~/.mindbot/data/memory",
                    "short_term_retention_days": 7,
                },
                "context": {"max_tokens": 8000, "compression": "truncate"},
                "session_journal": {"enabled": True, "path": "~/.mindbot/data/journal"},
                "multimodal": {"max_images": 10, "max_file_size_mb": 20.0},
                "channels": {"http": {"enabled": False}, "cli": {"enabled": False}},
            }
        ),
        encoding="utf-8",
    )


def test_build_benchmark_config_overrides_runtime_paths(tmp_path: Path) -> None:
    config_path = tmp_path / "settings.json"
    _write_config(config_path)

    config = build_benchmark_config(
        config_path=config_path,
        workspace_root=tmp_path / "workspace",
        benchmark_home=tmp_path / "home" / ".mindbot",
        model_ref="local-ollama/qwen3",
    )

    assert config.agent.workspace == str((tmp_path / "workspace").resolve())
    assert config.routing.auto is False
    assert config.agent.temperature == 0.0
    assert config.skills.enabled is False
    assert config.agent.tool_persistence.value == "full"


def test_load_scenarios_reads_real_tools_fixture_file() -> None:
    scenarios = load_scenarios(Path("benchmark/real-tools/scenarios.json"))

    ids = {scenario.id for scenario in scenarios}
    assert "rt01_find_release_code" in ids
    assert "rt13_fetch_recovery" in ids
    assert {scenario.category for scenario in scenarios} >= {
        "tool_selection",
        "parameter_precision",
        "multi_step_chains",
        "restraint_refusal",
        "error_recovery",
    }


def test_evaluate_scenario_scores_pass_with_correct_outputs_and_trace(tmp_path: Path) -> None:
    workspace = tmp_path
    target = workspace / "demo" / "result.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("done\n", encoding="utf-8")

    scenarios = load_scenarios(Path("benchmark/real-tools/scenarios.json"))
    scenario = next(item for item in scenarios if item.id == "rt03_build_summary_file")
    scenario.output_checks = [
        {"type": "file_exact", "path": "demo/result.txt", "value": "done\n"},
        {"type": "answer_contains", "value": "summary written"},
    ]
    scenario.trace_checks = [
        {"type": "requires_tools", "tools": ["read_file", "write_file"]},
        {"type": "stop_reason", "value": "completed"},
    ]

    response = AgentResponse(
        content="summary written",
        stop_reason=StopReason.COMPLETED,
        message_trace=[
            Message(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(id="call_1", name="read_file", arguments={"path": "demo/input.txt"}),
                    ToolCall(id="call_2", name="write_file", arguments={"path": "demo/result.txt", "content": "done"}),
                ],
                message_kind="assistant_tool_call",
            ),
            Message(
                role="tool",
                content="ok",
                tool_name="read_file",
                message_kind="tool_result",
            ),
            Message(
                role="tool",
                content="ok",
                tool_name="write_file",
                message_kind="tool_result",
            ),
        ],
    )

    result = evaluate_scenario(
        scenario,
        workspace=workspace,
        response=response,
        session_id="benchmark_demo",
        duration_ms=10,
    )

    assert result.status == "pass"
    assert result.points == 2
    assert result.category == scenario.category
    assert result.tools_used == ["read_file", "write_file"]
    assert result.observed_failure_tags == []


def test_evaluate_scenario_accepts_legacy_prefixed_output_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "rt02_precise_edit"
    target = workspace / "notes" / "status.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "# Launch Checklist\nOwner: qa-team\nStatus: ready-for-review\nReviewer: pending\n",
        encoding="utf-8",
    )

    scenarios = load_scenarios(Path("benchmark/real-tools/scenarios.json"))
    scenario = next(item for item in scenarios if item.id == "rt02_precise_edit")
    scenario.output_checks = [
        {
            "type": "file_exact",
            "path": "rt02_precise_edit/notes/status.md",
            "value": "# Launch Checklist\nOwner: qa-team\nStatus: ready-for-review\nReviewer: pending\n",
        }
    ]
    scenario.trace_checks = [{"type": "stop_reason", "value": "completed"}]

    response = AgentResponse(content="done", stop_reason=StopReason.COMPLETED, message_trace=[])

    result = evaluate_scenario(
        scenario,
        workspace=workspace,
        response=response,
        session_id="benchmark_legacy_path",
        duration_ms=5,
    )

    assert result.status == "pass"
    assert result.points == 2


def test_evaluate_scenario_derives_recovery_failure_tags(tmp_path: Path) -> None:
    workspace = tmp_path
    output = workspace / "output" / "total.txt"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("41\n", encoding="utf-8")

    scenarios = load_scenarios(Path("benchmark/real-tools/scenarios.json"))
    scenario = next(item for item in scenarios if item.id == "rt12_shell_command_recovery")

    response = AgentResponse(
        content="41",
        stop_reason=StopReason.COMPLETED,
        message_trace=[
            Message(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="exec_command",
                        arguments={"command": "wc -l data/metric.csv"},
                    )
                ],
                message_kind="assistant_tool_call",
            )
        ],
    )

    result = evaluate_scenario(
        scenario,
        workspace=workspace,
        response=response,
        session_id="benchmark_recovery",
        duration_ms=7,
    )

    assert result.status == "fail"
    assert set(result.observed_failure_tags) >= {"artifact_mismatch", "bad_arguments", "recovery_failure"}


def test_benchmark_tools_keeps_real_handlers() -> None:
    class FakeRegistry:
        def list_tools(self):
            return [
                type("Tool", (), {"name": "edit_file", "handler": object()})(),
                type("Tool", (), {"name": "fetch_url", "handler": object()})(),
                type("Tool", (), {"name": "other_tool", "handler": None})(),
            ]

    fake_bot = type(
        "FakeBot",
        (),
        {
            "_agent": type(
                "FakeMindAgent",
                (),
                {"_main_agent": type("FakeMainAgent", (), {"tool_registry": FakeRegistry()})()},
            )()
        },
    )()

    tools = benchmark_tools(fake_bot)

    assert {tool.name for tool in tools} == {"edit_file", "fetch_url"} & BENCHMARK_TOOL_NAMES
    assert all(getattr(tool, "handler", None) is not None for tool in tools)


def test_format_report_text_includes_category_and_failure_summaries() -> None:
    scenario = type(
        "Scenario",
        (),
        {
            "scenario_id": "rt-demo",
            "title": "Demo",
            "category": "tool_selection",
            "status": "fail",
            "points": 0,
            "output_checks": [],
            "trace_checks": [],
            "success_case": "",
            "failure_case": "",
            "expected_failure_tags": [],
            "observed_failure_tags": ["artifact_mismatch"],
            "final_answer": "",
            "stop_reason": "completed",
            "tools_used": ["read_file"],
            "workspace": "/tmp/demo",
            "session_id": "benchmark_demo",
            "duration_ms": 1,
            "raw_trace": [],
        },
    )()

    report = BenchmarkRunReport(
        benchmark_name="mindbot-real-tools",
        model="demo/model",
        config_path="/tmp/settings.json",
        workspace_root="/tmp/workspace",
        report_path=None,
        started_at=0.0,
        finished_at=1.0,
        scenarios=[scenario],
    )

    text = format_report_text(report)

    assert "Category Summary:" in text
    assert "Failure Tags:" in text
    assert "artifact_mismatch: 1" in text
