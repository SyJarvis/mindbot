#!/usr/bin/env python3
"""Run the mandatory MindBot release verification stages."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run(command: list[str], *, env: dict[str, str] | None = None, cwd: Path = ROOT) -> None:
    print(f"\n$ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def _venv_python(root: Path) -> Path:
    if os.name == "nt":
        return root / "Scripts" / "python.exe"
    return root / "bin" / "python"


def _venv_command(root: Path, name: str) -> Path:
    if os.name == "nt":
        return root / "Scripts" / f"{name}.exe"
    return root / "bin" / name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run regression, build, installed-wheel, and real SDK release tests."
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Optional settings.json. When omitted, use sourced MINDBOT_* variables.",
    )
    parser.add_argument(
        "--with-regression",
        action="store_true",
        help="Also run the normal non-integration pytest suite before release tests.",
    )
    args = parser.parse_args(argv)

    config_path = args.config.expanduser().resolve() if args.config else None
    if config_path is not None and not config_path.is_file():
        parser.error(f"Config file does not exist: {config_path}")
    if config_path is None:
        required = ["MINDBOT_PROVIDER", "MINDBOT_BASE_URL", "MINDBOT_MODELS"]
        missing = [name for name in required if not os.environ.get(name)]
        if missing:
            parser.error(
                "Pass --config or source provider settings first. Missing: "
                + ", ".join(missing)
            )

    if args.with_regression:
        _run([sys.executable, "-m", "pytest", "-m", "not integration", "-q"])

    _run(["uv", "build"])
    wheels = sorted((ROOT / "dist").glob("mindbot-*.whl"), key=lambda path: path.stat().st_mtime)
    if not wheels:
        raise RuntimeError("uv build did not produce a MindBot wheel")
    wheel = wheels[-1]

    functional_env = os.environ.copy()
    functional_env.update({
        "MINDBOT_RUN_SDK_FUNCTIONAL": "1",
        "MINDBOT_REPOSITORY_ROOT": str(ROOT),
    })
    if config_path is not None:
        functional_env["MINDBOT_SDK_TEST_CONFIG"] = str(config_path)

    with tempfile.TemporaryDirectory(prefix="mindbot-release-venv-") as tmp:
        venv_root = Path(tmp)
        _run(
            [
                "uv",
                "venv",
                "--python",
                sys.executable,
                "--no-project",
                str(venv_root),
            ]
        )
        python = _venv_python(venv_root)
        mindbot_cli = _venv_command(venv_root, "mindbot")

        _run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(python),
                "--reinstall",
                str(wheel),
            ]
        )
        _run([str(mindbot_cli), "--version"], cwd=Path(tmp))
        _run(
            [str(python), str(ROOT / "tests/package/installed_sdk_check.py")],
            env=functional_env,
            cwd=Path(tmp),
        )

    _run(
        [sys.executable, "-m", "pytest", "tests/release", "-m", "release", "-q"],
        env=functional_env,
    )
    print("\nRelease verification passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
