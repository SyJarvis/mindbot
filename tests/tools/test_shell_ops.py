from __future__ import annotations

from pathlib import Path

import pytest

from mindbot.tools.shell_ops import create_shell_tools


@pytest.fixture()
def anyio_backend() -> str:
    return "asyncio"


def _tool_map(
    workspace: Path,
    *,
    allowed_paths: list[Path | str] | None = None,
) -> dict[str, object]:
    tools = create_shell_tools(workspace, allowed_paths=allowed_paths)
    return {tool.name: tool for tool in tools}


@pytest.mark.anyio
async def test_exec_command_allows_whitelisted_working_dir(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    system_dir = tmp_path / "system"
    system_dir.mkdir()
    tools = _tool_map(workspace, allowed_paths=[system_dir])

    result = await tools["exec_command"].handler("pwd", working_dir=str(system_dir))  # type: ignore[union-attr]

    assert str(system_dir) in result


@pytest.mark.anyio
async def test_exec_command_rejects_unlisted_working_dir(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    system_dir = tmp_path / "system"
    system_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    tools = _tool_map(workspace, allowed_paths=[system_dir])

    result = await tools["exec_command"].handler("pwd", working_dir=str(outside))  # type: ignore[union-attr]

    assert "outside the allowed paths" in result


@pytest.mark.anyio
async def test_exec_command_uses_workspace_as_default_cwd(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    tools = _tool_map(workspace)

    result = await tools["exec_command"].handler("pwd")  # type: ignore[union-attr]

    assert str(workspace) in result
