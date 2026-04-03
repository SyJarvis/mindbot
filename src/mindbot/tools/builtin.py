"""Assembly helpers for MindBot built-in tools."""

from __future__ import annotations

from pathlib import Path

from mindbot.capability.backends.tooling.models import Tool
from mindbot.tools.file_ops import create_file_tools
from mindbot.tools.mindbot_ops import create_mindbot_tools
from mindbot.tools.shell_ops import create_shell_tools
from mindbot.tools.web_ops import create_web_tools


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
    tools.extend(create_mindbot_tools(root))
    tools.extend(create_web_tools())
    return tools
