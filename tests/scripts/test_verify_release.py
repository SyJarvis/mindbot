"""Regression tests for the release verification command."""

from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_release.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("verify_release_test_module", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_skips_regression_and_uses_clean_uv_environment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    root = tmp_path / "repo"
    dist = root / "dist"
    dist.mkdir(parents=True)
    wheel = dist / "mindbot-0.4.0-py3-none-any.whl"
    wheel.write_bytes(b"wheel")

    commands: list[list[str]] = []
    monkeypatch.setattr(module, "ROOT", root)
    monkeypatch.setattr(module, "_run", lambda command, **kwargs: commands.append(command))
    monkeypatch.setenv("MINDBOT_PROVIDER", "openai")
    monkeypatch.setenv("MINDBOT_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("MINDBOT_MODELS", "test-model")

    assert module.main([]) == 0

    assert not any("pytest" in command for command in commands[:-1])
    venv_command = next(command for command in commands if command[:2] == ["uv", "venv"])
    assert "--system-site-packages" not in venv_command

    install_command = next(
        command for command in commands if command[:3] == ["uv", "pip", "install"]
    )
    assert "--no-deps" not in install_command


def test_with_regression_runs_non_integration_suite(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    root = tmp_path / "repo"
    dist = root / "dist"
    dist.mkdir(parents=True)
    (dist / "mindbot-0.4.0-py3-none-any.whl").write_bytes(b"wheel")

    commands: list[list[str]] = []
    monkeypatch.setattr(module, "ROOT", root)
    monkeypatch.setattr(module, "_run", lambda command, **kwargs: commands.append(command))
    monkeypatch.setenv("MINDBOT_PROVIDER", "openai")
    monkeypatch.setenv("MINDBOT_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("MINDBOT_MODELS", "test-model")

    assert module.main(["--with-regression"]) == 0

    assert commands[0][1:] == ["-m", "pytest", "-m", "not integration", "-q"]
