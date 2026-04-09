from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from mindbot.cli import app


def test_toolcall15_adapter_invokes_server_with_config(tmp_path, monkeypatch) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

    config_root = fake_home / ".mindbot"
    config_root.mkdir(parents=True)
    config_path = config_root / "settings.json"
    config_path.write_text("{}", encoding="utf-8")

    called: dict[str, object] = {}

    async def fake_server(**kwargs):
        called.update(kwargs)

    import mindbot.benchmarking as benchmarking

    monkeypatch.setattr(benchmarking, "serve_toolcall15_adapter", fake_server)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["toolcall15-adapter", "--port", "11435", "--model", "local-ollama/qwen3"],
    )

    assert result.exit_code == 0
    assert called["port"] == 11435
    assert called["default_model"] == "local-ollama/qwen3"
    assert called["config_path"] == config_path


def test_toolcall15_adapter_requires_config(monkeypatch) -> None:
    fake_home = Path("/tmp/nonexistent-home-for-toolcall15")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

    runner = CliRunner()
    result = runner.invoke(app, ["toolcall15-adapter", "--model", "local-ollama/qwen3"])

    assert result.exit_code == 1
    assert "Config not found" in result.stdout
