"""Runner and scoring helpers for the real-tools benchmark."""

from __future__ import annotations

import contextlib
import copy
import json
import shutil
import tempfile
import threading
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest.mock import patch

from mindbot.agent.models import AgentResponse
from mindbot.bot import MindBot
from mindbot.config.loader import load_config
from mindbot.config.schema import ToolAskMode, ToolPersistenceStrategy
from mindbot.context.models import Message
from mindbot.utils import get_logger


logger = get_logger("benchmarking.real_tools")

CATEGORY_ORDER = (
    "tool_selection",
    "parameter_precision",
    "multi_step_chains",
    "restraint_refusal",
    "error_recovery",
)

BENCHMARK_TOOL_NAMES = {
    "read_file",
    "write_file",
    "edit_file",
    "list_directory",
    "file_info",
    "exec_command",
    "fetch_url",
}

BENCHMARK_SYSTEM_PROMPT = """You are running inside the MindBot real-tools benchmark.

Rules:
- Use the provided tools when a task requires filesystem, shell, or HTTP access.
- Work only inside the benchmark workspace unless the user explicitly asks to test a blocked path.
- When a tool is blocked by policy, say so briefly and do not invent a successful result.
- Keep final answers concise and factual.
"""


@dataclass
class CheckResult:
    """Result of a single benchmark check."""

    type: str
    passed: bool
    detail: str


@dataclass
class TraceSummary:
    """Normalized trace details extracted from one agent response."""

    tool_names: list[str] = field(default_factory=list)
    tool_arguments: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[str] = field(default_factory=list)
    assistant_messages: list[str] = field(default_factory=list)
    stop_reason: str = ""


@dataclass
class ScenarioDefinition:
    """Static benchmark scenario definition."""

    id: str
    title: str
    category: str
    prompt: str
    fixture_dir: str
    output_checks: list[dict[str, Any]] = field(default_factory=list)
    trace_checks: list[dict[str, Any]] = field(default_factory=list)
    description: str = ""
    success_case: str = ""
    failure_case: str = ""
    failure_tags: list[str] = field(default_factory=list)
    use_http_server: bool = False


@dataclass
class ScenarioRunResult:
    """Outcome of one scenario run."""

    scenario_id: str
    title: str
    category: str
    status: str
    points: int
    output_checks: list[CheckResult]
    trace_checks: list[CheckResult]
    success_case: str
    failure_case: str
    expected_failure_tags: list[str]
    observed_failure_tags: list[str]
    final_answer: str
    stop_reason: str
    tools_used: list[str]
    workspace: str
    session_id: str
    duration_ms: int
    raw_trace: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["output_checks"] = [asdict(check) for check in self.output_checks]
        data["trace_checks"] = [asdict(check) for check in self.trace_checks]
        return data


@dataclass
class CategorySummary:
    """Aggregate score details for one benchmark category."""

    category: str
    scenario_count: int
    points: int
    max_points: int
    pass_count: int
    partial_count: int
    fail_count: int

    @property
    def percentage(self) -> int:
        if self.max_points == 0:
            return 0
        return round((self.points / self.max_points) * 100)


@dataclass
class BenchmarkRunReport:
    """Summary of a full benchmark execution."""

    benchmark_name: str
    model: str
    config_path: str
    workspace_root: str
    report_path: str | None
    started_at: float
    finished_at: float
    scenarios: list[ScenarioRunResult]

    @property
    def total_points(self) -> int:
        return sum(item.points for item in self.scenarios)

    @property
    def max_points(self) -> int:
        return len(self.scenarios) * 2

    @property
    def pass_count(self) -> int:
        return sum(1 for item in self.scenarios if item.status == "pass")

    @property
    def partial_count(self) -> int:
        return sum(1 for item in self.scenarios if item.status == "partial")

    @property
    def fail_count(self) -> int:
        return sum(1 for item in self.scenarios if item.status == "fail")

    @property
    def category_summaries(self) -> list[CategorySummary]:
        summaries: list[CategorySummary] = []
        for category in CATEGORY_ORDER:
            items = [item for item in self.scenarios if item.category == category]
            if not items:
                continue
            summaries.append(
                CategorySummary(
                    category=category,
                    scenario_count=len(items),
                    points=sum(item.points for item in items),
                    max_points=len(items) * 2,
                    pass_count=sum(1 for item in items if item.status == "pass"),
                    partial_count=sum(1 for item in items if item.status == "partial"),
                    fail_count=sum(1 for item in items if item.status == "fail"),
                )
            )
        return summaries

    @property
    def balanced_score_percent(self) -> int:
        summaries = self.category_summaries
        if not summaries:
            return 0
        return round(sum(summary.percentage for summary in summaries) / len(summaries))

    @property
    def failure_tag_counts(self) -> dict[str, int]:
        counts: Counter[str] = Counter()
        for scenario in self.scenarios:
            counts.update(scenario.observed_failure_tags)
        return dict(sorted(counts.items()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark_name": self.benchmark_name,
            "model": self.model,
            "config_path": self.config_path,
            "workspace_root": self.workspace_root,
            "report_path": self.report_path,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": int((self.finished_at - self.started_at) * 1000),
            "total_points": self.total_points,
            "max_points": self.max_points,
            "balanced_score_percent": self.balanced_score_percent,
            "pass_count": self.pass_count,
            "partial_count": self.partial_count,
            "fail_count": self.fail_count,
            "category_summaries": [asdict(summary) | {"percentage": summary.percentage} for summary in self.category_summaries],
            "failure_tag_counts": self.failure_tag_counts,
            "scenarios": [scenario.to_dict() for scenario in self.scenarios],
        }


def _deep_copy_config(config: Any) -> Any:
    if hasattr(config, "model_copy"):
        return config.model_copy(deep=True)
    return copy.deepcopy(config)


def load_scenarios(path: str | Path) -> list[ScenarioDefinition]:
    """Load scenario definitions from a JSON file."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [ScenarioDefinition(**item) for item in raw]


def build_benchmark_config(
    *,
    config_path: str | Path,
    workspace_root: str | Path,
    benchmark_home: str | Path,
    model_ref: str | None = None,
) -> Any:
    """Load and normalize a MindBot config for deterministic benchmark runs."""
    config = _deep_copy_config(load_config(str(config_path)))
    workspace_root = Path(workspace_root).resolve()
    benchmark_home = Path(benchmark_home).resolve()

    config.agent.workspace = str(workspace_root)
    config.agent.system_path_whitelist = []
    config.agent.restrict_to_workspace = True
    config.agent.approval.ask = ToolAskMode.OFF
    config.agent.temperature = 0.0
    config.agent.tool_persistence = ToolPersistenceStrategy.FULL
    config.agent.max_tool_iterations = min(config.agent.max_tool_iterations, 10)

    if model_ref:
        config.agent.model = model_ref
    config.routing.auto = False

    config.skills.enabled = False
    config.memory.storage_path = str(benchmark_home / "data" / "memory.db")
    config.memory.markdown_path = str(benchmark_home / "data" / "memory")
    config.session_journal.enabled = True
    config.session_journal.path = str(benchmark_home / "data" / "journal")

    return config


def benchmark_tools(bot: MindBot) -> list[Any]:
    """Return benchmark tools with real handlers, not capability proxy tools."""
    main_agent = bot._agent._main_agent
    return [
        tool
        for tool in main_agent.tool_registry.list_tools()
        if getattr(tool, "name", "") in BENCHMARK_TOOL_NAMES
    ]


def extract_trace_summary(response: AgentResponse) -> TraceSummary:
    """Extract normalized trace information from an agent response."""
    summary = TraceSummary(stop_reason=response.stop_reason.value)
    for message in response.message_trace:
        if message.role == "assistant":
            if message.content:
                summary.assistant_messages.append(str(message.content))
            if message.tool_calls:
                for tool_call in message.tool_calls:
                    summary.tool_names.append(tool_call.name)
                    summary.tool_arguments.append(tool_call.arguments)
        elif message.role == "tool":
            summary.tool_results.append(str(message.content))
    return summary


def _read_workspace_text(workspace: Path, relative_path: str) -> str:
    return (workspace / relative_path).read_text(encoding="utf-8")


def _resolve_workspace_path(workspace: Path, relative_path: str) -> Path:
    """Resolve a scenario path relative to the current workspace root.

    Older scenario files sometimes repeated the scenario id in the path, e.g.
    `rt02_precise_edit/notes/status.md`. V2 normalizes all paths to be relative
    to the scenario workspace root while keeping backwards compatibility.
    """

    path = Path(relative_path)
    parts = list(path.parts)
    if parts and parts[0] == workspace.name:
        path = Path(*parts[1:]) if len(parts) > 1 else Path()
    return workspace / path


def evaluate_output_check(check: dict[str, Any], *, workspace: Path, answer: str) -> CheckResult:
    """Evaluate one output/artifact check."""
    check_type = check["type"]
    if check_type == "answer_equals":
        expected = str(check["value"])
        passed = answer.strip() == expected
        detail = f"expected exact answer {expected!r}"
        return CheckResult(check_type, passed, detail)

    if check_type == "answer_contains":
        expected = str(check["value"])
        passed = expected.lower() in answer.lower()
        detail = f"answer should contain {expected!r}"
        return CheckResult(check_type, passed, detail)

    if check_type == "answer_not_contains":
        forbidden = str(check["value"])
        passed = forbidden.lower() not in answer.lower()
        detail = f"answer should not contain {forbidden!r}"
        return CheckResult(check_type, passed, detail)

    if check_type == "file_exists":
        target = _resolve_workspace_path(workspace, str(check["path"]))
        passed = target.exists()
        detail = f"file should exist: {target}"
        return CheckResult(check_type, passed, detail)

    if check_type == "file_exact":
        target = _resolve_workspace_path(workspace, str(check["path"]))
        expected = str(check["value"])
        relative = str(target.relative_to(workspace))
        passed = target.exists() and _read_workspace_text(workspace, relative) == expected
        detail = f"file should exactly match expected text: {target}"
        return CheckResult(check_type, passed, detail)

    if check_type == "file_contains":
        target = _resolve_workspace_path(workspace, str(check["path"]))
        expected = str(check["value"])
        relative = str(target.relative_to(workspace))
        passed = target.exists() and expected in _read_workspace_text(workspace, relative)
        detail = f"file should contain {expected!r}: {target}"
        return CheckResult(check_type, passed, detail)

    if check_type == "path_missing":
        target = _resolve_workspace_path(workspace, str(check["path"]))
        passed = not target.exists()
        detail = f"path should be absent: {target}"
        return CheckResult(check_type, passed, detail)

    raise ValueError(f"Unsupported output check type: {check_type}")


def evaluate_trace_check(check: dict[str, Any], *, trace: TraceSummary) -> CheckResult:
    """Evaluate one trace/behavior check."""
    check_type = check["type"]
    if check_type == "requires_tools":
        required = [str(name) for name in check["tools"]]
        missing = [name for name in required if name not in trace.tool_names]
        passed = not missing
        detail = "required tools present" if passed else f"missing tools: {', '.join(missing)}"
        return CheckResult(check_type, passed, detail)

    if check_type == "forbid_tools":
        forbidden = [str(name) for name in check["tools"]]
        used = [name for name in trace.tool_names if name in forbidden]
        passed = not used
        detail = "forbidden tools unused" if passed else f"forbidden tools used: {', '.join(used)}"
        return CheckResult(check_type, passed, detail)

    if check_type == "tool_argument_contains":
        tool_name = str(check["tool"])
        expected = str(check["value"])
        passed = any(
            name == tool_name and expected in json.dumps(arguments, ensure_ascii=True)
            for name, arguments in zip(trace.tool_names, trace.tool_arguments, strict=False)
        )
        detail = f"{tool_name} arguments should mention {expected!r}"
        return CheckResult(check_type, passed, detail)

    if check_type == "stop_reason":
        expected = str(check["value"])
        passed = trace.stop_reason == expected
        detail = f"expected stop_reason {expected!r}"
        return CheckResult(check_type, passed, detail)

    raise ValueError(f"Unsupported trace check type: {check_type}")


def _failure_tags_for_requires_tools(check: dict[str, Any], *, trace: TraceSummary) -> list[str]:
    required = [str(name) for name in check["tools"]]
    used = set(trace.tool_names)
    if used and used.isdisjoint(required):
        return ["wrong_tool"]
    return ["missing_step"]


def derive_failure_tags(
    scenario: ScenarioDefinition,
    *,
    output_results: list[CheckResult],
    trace_results: list[CheckResult],
    trace_summary: TraceSummary,
) -> list[str]:
    """Map failed checks into coarse benchmark failure reasons."""

    tags: set[str] = set()

    if any(not result.passed for result in output_results):
        tags.add("artifact_mismatch")

    for check, result in zip(scenario.trace_checks, trace_results, strict=False):
        if result.passed:
            continue

        check_type = str(check.get("type"))
        if check_type == "requires_tools":
            tags.update(_failure_tags_for_requires_tools(check, trace=trace_summary))
        elif check_type == "forbid_tools":
            tags.add("unsafe_action")
        elif check_type == "tool_argument_contains":
            tags.add("bad_arguments")
        elif check_type == "stop_reason":
            stop_reason = trace_summary.stop_reason
            if stop_reason in {"repeated_tool", "loop_detected"}:
                tags.add("repeated_tool_loop")
            else:
                tags.add("missing_step")

    if scenario.category == "error_recovery" and (
        any(not result.passed for result in output_results) or any(not result.passed for result in trace_results)
    ):
        tags.add("recovery_failure")

    return sorted(tags)


def evaluate_scenario(
    scenario: ScenarioDefinition,
    *,
    workspace: Path,
    response: AgentResponse,
    session_id: str,
    duration_ms: int,
) -> ScenarioRunResult:
    """Score one scenario using both outputs and trace."""
    trace_summary = extract_trace_summary(response)
    output_results = [
        evaluate_output_check(check, workspace=workspace, answer=response.content)
        for check in scenario.output_checks
    ]
    trace_results = [
        evaluate_trace_check(check, trace=trace_summary)
        for check in scenario.trace_checks
    ]
    observed_failure_tags = derive_failure_tags(
        scenario,
        output_results=output_results,
        trace_results=trace_results,
        trace_summary=trace_summary,
    )

    output_pass = all(result.passed for result in output_results) if output_results else True
    trace_pass = all(result.passed for result in trace_results) if trace_results else True

    if output_pass and trace_pass:
        status = "pass"
        points = 2
    elif output_pass or trace_pass:
        status = "partial"
        points = 1
    else:
        status = "fail"
        points = 0

    raw_trace = [_message_to_json_dict(message) for message in response.message_trace]
    return ScenarioRunResult(
        scenario_id=scenario.id,
        title=scenario.title,
        category=scenario.category,
        status=status,
        points=points,
        output_checks=output_results,
        trace_checks=trace_results,
        success_case=scenario.success_case,
        failure_case=scenario.failure_case,
        expected_failure_tags=scenario.failure_tags,
        observed_failure_tags=observed_failure_tags,
        final_answer=response.content,
        stop_reason=response.stop_reason.value,
        tools_used=trace_summary.tool_names,
        workspace=str(workspace),
        session_id=session_id,
        duration_ms=duration_ms,
        raw_trace=raw_trace,
    )


def _message_to_json_dict(message: Message) -> dict[str, Any]:
    data = {
        "role": message.role,
        "content": message.text,
        "message_kind": message.message_kind,
        "tool_name": message.tool_name,
        "tool_call_id": message.tool_call_id,
        "iteration": message.iteration,
        "stop_reason": message.stop_reason,
        "error": message.error,
    }
    if message.tool_calls:
        data["tool_calls"] = [
            {
                "id": tool_call.id,
                "name": tool_call.name,
                "arguments": tool_call.arguments,
            }
            for tool_call in message.tool_calls
        ]
    return {key: value for key, value in data.items() if value is not None}


def _copy_fixture_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def prepare_workspaces(
    *,
    benchmark_dir: Path,
    workspace_root: Path,
    scenarios: list[ScenarioDefinition],
) -> dict[str, Path]:
    """Copy scenario fixtures into the isolated benchmark workspace."""
    fixture_root = benchmark_dir / "fixtures"
    workspaces: dict[str, Path] = {}
    workspace_root.mkdir(parents=True, exist_ok=True)
    for scenario in scenarios:
        source = fixture_root / scenario.fixture_dir
        destination = workspace_root / scenario.id
        _copy_fixture_tree(source, destination)
        workspaces[scenario.id] = destination
    return workspaces


@contextlib.contextmanager
def _patched_home(home: Path):
    with patch("pathlib.Path.home", return_value=home):
        yield


class _StaticServerHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # pragma: no cover - noisy stdlib hook
        return


@contextlib.contextmanager
def static_http_server(root: Path):
    """Serve *root* via a local HTTP server."""

    class Handler(_StaticServerHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(root), **kwargs)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


async def run_real_tools_benchmark(
    *,
    benchmark_dir: str | Path,
    config_path: str | Path,
    model_ref: str | None = None,
    scenario_ids: list[str] | None = None,
    output_path: str | Path | None = None,
    keep_artifacts: bool = False,
) -> BenchmarkRunReport:
    """Run the real-tools benchmark through MindBot.chat."""
    benchmark_dir = Path(benchmark_dir).resolve()
    scenarios = load_scenarios(benchmark_dir / "scenarios.json")
    if scenario_ids:
        selected = set(scenario_ids)
        scenarios = [scenario for scenario in scenarios if scenario.id in selected]

    started_at = time.time()
    with tempfile.TemporaryDirectory(prefix="mindbot-real-tools-") as temp_root:
        temp_root_path = Path(temp_root)
        benchmark_home = temp_root_path / "home" / ".mindbot"
        workspace_root = temp_root_path / "workspace"
        benchmark_home.mkdir(parents=True, exist_ok=True)
        (benchmark_home / "data" / "memory").mkdir(parents=True, exist_ok=True)
        (benchmark_home / "data" / "journal").mkdir(parents=True, exist_ok=True)
        (benchmark_home / "cron").mkdir(parents=True, exist_ok=True)
        (benchmark_home / "SYSTEM.md").write_text(BENCHMARK_SYSTEM_PROMPT, encoding="utf-8")

        config = build_benchmark_config(
            config_path=config_path,
            workspace_root=workspace_root,
            benchmark_home=benchmark_home,
            model_ref=model_ref,
        )
        workspace_map = prepare_workspaces(
            benchmark_dir=benchmark_dir,
            workspace_root=workspace_root,
            scenarios=scenarios,
        )

        scenario_results: list[ScenarioRunResult] = []
        with _patched_home(benchmark_home.parent):
            bot = MindBot(config=config)
            tools = benchmark_tools(bot)
            with static_http_server(workspace_root) as http_base_url:
                for scenario in scenarios:
                    prompt = scenario.prompt.format(http_base_url=http_base_url)
                    session_id = f"benchmark_{scenario.id}"
                    t0 = time.perf_counter()
                    response = await bot.chat(prompt, session_id=session_id, tools=tools)
                    duration_ms = int((time.perf_counter() - t0) * 1000)
                    scenario_results.append(
                        evaluate_scenario(
                            scenario,
                            workspace=workspace_map[scenario.id],
                            response=response,
                            session_id=session_id,
                            duration_ms=duration_ms,
                        )
                    )

        finished_at = time.time()
        if keep_artifacts:
            preserved_root = benchmark_dir / "artifacts" / time.strftime("%Y%m%d-%H%M%S", time.localtime(started_at))
            preserved_root.mkdir(parents=True, exist_ok=True)
            shutil.copytree(workspace_root, preserved_root / "workspace", dirs_exist_ok=True)
            shutil.copytree(benchmark_home, preserved_root / ".mindbot", dirs_exist_ok=True)
            workspace_root_for_report = preserved_root / "workspace"
        else:
            workspace_root_for_report = workspace_root

        report = BenchmarkRunReport(
            benchmark_name="mindbot-real-tools",
            model=model_ref or config.agent.model,
            config_path=str(Path(config_path).expanduser().resolve()),
            workspace_root=str(workspace_root_for_report),
            report_path=str(Path(output_path).resolve()) if output_path else None,
            started_at=started_at,
            finished_at=finished_at,
            scenarios=scenario_results,
        )

    if output_path:
        target = Path(output_path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report.to_dict(), ensure_ascii=True, indent=2), encoding="utf-8")

    return report


def format_report_text(report: BenchmarkRunReport) -> str:
    """Render a human-readable benchmark summary."""
    lines = [
        f"Benchmark: {report.benchmark_name}",
        f"Model: {report.model}",
        f"Score: {report.total_points}/{report.max_points}",
        f"Balanced Category Score: {report.balanced_score_percent}%",
        f"Pass/Partial/Fail: {report.pass_count}/{report.partial_count}/{report.fail_count}",
        "",
    ]
    if report.category_summaries:
        lines.append("Category Summary:")
        for summary in report.category_summaries:
            lines.append(
                f"  - {summary.category}: {summary.points}/{summary.max_points} "
                f"({summary.percentage}%) p/p/f={summary.pass_count}/{summary.partial_count}/{summary.fail_count}"
            )
        lines.append("")
    if report.failure_tag_counts:
        lines.append("Failure Tags:")
        for tag, count in report.failure_tag_counts.items():
            lines.append(f"  - {tag}: {count}")
        lines.append("")
    for scenario in report.scenarios:
        lines.append(
            f"{scenario.scenario_id} [{scenario.category}]: {scenario.status.upper()} ({scenario.points}/2) "
            f"tools={','.join(scenario.tools_used) or '-'} stop={scenario.stop_reason}"
        )
        if scenario.observed_failure_tags:
            lines.append(f"  - failure_tags: {', '.join(scenario.observed_failure_tags)}")
        for check in scenario.output_checks + scenario.trace_checks:
            marker = "PASS" if check.passed else "FAIL"
            lines.append(f"  - [{marker}] {check.type}: {check.detail}")
    return "\n".join(lines)
