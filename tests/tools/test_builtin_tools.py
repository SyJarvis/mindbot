from __future__ import annotations

from pathlib import Path

import pytest

from mindbot.tools import create_builtin_tools


def _tool_map(tmp_path: Path) -> dict[str, object]:
    tools = create_builtin_tools(tmp_path)
    return {tool.name: tool for tool in tools}


def test_read_file_uses_workspace_guard(tmp_path: Path) -> None:
    tools = _tool_map(tmp_path)
    target = tmp_path / "note.txt"
    target.write_text("alpha\nbeta\n", encoding="utf-8")

    result = tools["read_file"].handler("note.txt")  # type: ignore[union-attr]
    assert "1|alpha" in result
    assert "2|beta" in result

    outside = tmp_path.parent / "outside.txt"
    outside.write_text("escape", encoding="utf-8")
    blocked = tools["read_file"].handler(str(outside))  # type: ignore[union-attr]
    assert "outside the allowed workspace" in blocked


def test_edit_file_requires_unique_match(tmp_path: Path) -> None:
    tools = _tool_map(tmp_path)
    target = tmp_path / "dup.txt"
    target.write_text("x\nx\n", encoding="utf-8")

    result = tools["edit_file"].handler("dup.txt", "x", "y")  # type: ignore[union-attr]
    assert "appears 2 times" in result


@pytest.mark.asyncio
async def test_exec_command_blocks_dangerous_command(tmp_path: Path) -> None:
    tools = _tool_map(tmp_path)
    result = await tools["exec_command"].handler("rm -rf /")  # type: ignore[union-attr]
    assert "blocked by safety policy" in result


@pytest.mark.asyncio
async def test_exec_command_runs_safe_command(tmp_path: Path) -> None:
    tools = _tool_map(tmp_path)
    result = await tools["exec_command"].handler("printf 'hello'")  # type: ignore[union-attr]
    assert "hello" in result


@pytest.mark.asyncio
async def test_web_search_reports_missing_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    tools = _tool_map(tmp_path)
    result = await tools["web_search"].handler("mindbot")  # type: ignore[union-attr]
    assert "BRAVE_API_KEY" in result


def test_list_directory_outside_workspace_rejected(tmp_path: Path) -> None:
    """User question: 查看~/research目录下有啥文件...

    When workspace is the server cwd (e.g. project root), ~/research is outside
    the allowed directory. list_directory must return the workspace error
    instead of listing the user's home.
    """
    tools = _tool_map(tmp_path)
    result = tools["list_directory"].handler("~/research")  # type: ignore[union-attr]
    assert "outside the allowed workspace" in result
    assert "~/research" in result or "research" in result
