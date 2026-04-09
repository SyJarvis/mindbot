#!/usr/bin/env python3
"""Run the MindBot real-tools benchmark."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from mindbot.benchmarking import format_report_text, run_real_tools_benchmark


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the MindBot real-tools benchmark.")
    parser.add_argument(
        "--config-path",
        default=str(Path.home() / ".mindbot" / "settings.json"),
        help="Path to the MindBot settings.json file.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Optional fixed instance/model reference to benchmark.",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        dest="scenarios",
        default=None,
        help="Run only the given scenario ID. Repeat to select multiple scenarios.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional path for a JSON benchmark report.",
    )
    parser.add_argument(
        "--keep-artifacts",
        action="store_true",
        help="Preserve the temporary workspace and benchmark home under benchmark/real-tools/artifacts.",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    benchmark_dir = Path(__file__).resolve().parent
    report = await run_real_tools_benchmark(
        benchmark_dir=benchmark_dir,
        config_path=args.config_path,
        model_ref=args.model,
        scenario_ids=args.scenarios,
        output_path=args.output,
        keep_artifacts=args.keep_artifacts,
    )
    print(format_report_text(report))
    if args.output:
        print(f"\nJSON report: {Path(args.output).expanduser().resolve()}")


if __name__ == "__main__":
    asyncio.run(main())
