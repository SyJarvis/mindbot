"""Assembly helpers for MindBot built-in tools."""

from __future__ import annotations

from pathlib import Path

from src.mindbot.capability.backends.tooling.models import Tool
from src.mindbot.tools.file_ops import create_file_tools
from src.mindbot.tools.shell_ops import create_shell_tools
from src.mindbot.tools.web_ops import create_web_tools


def create_builtin_tools(
    workspace: Path | None = None,
    *,
    restrict_to_workspace: bool = True,
) -> list[Tool]:
    """Create the default built-in tool set."""
    root = (workspace or Path.cwd()).expanduser().resolve()
    tools: list[Tool] = []
    tools.extend(
        create_file_tools(
            root,
            restrict_to_workspace=restrict_to_workspace,
        )
    )
    tools.extend(
        create_shell_tools(
            root,
            restrict_to_workspace=restrict_to_workspace,
        )
    )
    tools.extend(create_web_tools())
    return tools
