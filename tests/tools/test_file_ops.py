from __future__ import annotations

from pathlib import Path

from mindbot.tools.file_ops import create_file_tools


def _tool_map(
    workspace: Path,
    *,
    allowed_paths: list[Path | str] | None = None,
) -> dict[str, object]:
    tools = create_file_tools(workspace, allowed_paths=allowed_paths)
    return {tool.name: tool for tool in tools}


def test_read_file_allows_system_whitelist(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    system_dir = tmp_path / "system"
    system_dir.mkdir()
    target = system_dir / "note.txt"
    target.write_text("whitelisted", encoding="utf-8")

    tools = _tool_map(workspace, allowed_paths=[system_dir])
    result = tools["read_file"].handler(str(target))  # type: ignore[union-attr]

    assert "1|whitelisted" in result


def test_write_file_allows_system_whitelist(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    system_dir = tmp_path / "system"
    system_dir.mkdir()
    target = system_dir / "written.txt"

    tools = _tool_map(workspace, allowed_paths=[system_dir])
    result = tools["write_file"].handler(str(target), "hello")  # type: ignore[union-attr]

    assert "Successfully wrote" in result
    assert target.read_text(encoding="utf-8") == "hello"


def test_allowed_root_covers_nested_subdirectories(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    system_dir = tmp_path / "system"
    nested_dir = system_dir / "nested" / "docs"
    nested_dir.mkdir(parents=True)
    target = nested_dir / "note.txt"
    target.write_text("nested", encoding="utf-8")

    tools = _tool_map(workspace, allowed_paths=[system_dir])
    result = tools["read_file"].handler(str(target))  # type: ignore[union-attr]

    assert "1|nested" in result


def test_file_ops_reject_paths_outside_allowed_roots(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    system_dir = tmp_path / "system"
    system_dir.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("nope", encoding="utf-8")

    tools = _tool_map(workspace, allowed_paths=[system_dir])
    result = tools["read_file"].handler(str(outside))  # type: ignore[union-attr]

    assert "outside the allowed paths" in result
