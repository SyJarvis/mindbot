"""Built-in shell tools."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
import os
import re
from pathlib import Path

from mindbot.capability.backends.tooling.models import Tool
from mindbot.tools.path_policy import is_within_allowed_roots, resolve_allowed_roots

_DANGEROUS_PATTERNS = [
    r"\brm\s+-[rf]{1,2}\b",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r"\bshutdown\b",
    r"\breboot\b",
    r">\s*/dev/",
]


def create_shell_tools(
    workspace: Path | str,
    *,
    restrict_to_workspace: bool = True,
    allowed_paths: Sequence[Path | str] | None = None,
    default_timeout: int = 30,
) -> list[Tool]:
    """Create shell tools bound to *workspace*."""
    root, allowed_roots = resolve_allowed_roots(
        workspace,
        restrict_to_workspace=restrict_to_workspace,
        allowed_paths=allowed_paths,
    )

    async def exec_command(
        command: str,
        timeout: int = default_timeout,
        working_dir: str | None = None,
        capture_stderr: bool = True,
    ) -> str:
        command = command.strip()
        if not command:
            return "Error: command must not be empty"

        lowered = command.lower()
        for pattern in _DANGEROUS_PATTERNS:
            if re.search(pattern, lowered):
                return "Error: command blocked by safety policy"

        cwd = root
        if working_dir:
            candidate = Path(working_dir).expanduser()
            if not candidate.is_absolute():
                candidate = root / candidate
            try:
                cwd = candidate.resolve()
                if not is_within_allowed_roots(cwd, allowed_roots):
                    allowed_text = ", ".join(str(path) for path in allowed_roots)
                    return (
                        "Error: working_dir is outside the allowed paths: "
                        f"{working_dir} (allowed: {allowed_text})"
                    )
            except OSError as exc:
                return f"Error: invalid working_dir: {exc}"

        if restrict_to_workspace and ("../" in command or "..\\" in command):
            return "Error: command blocked due to path traversal"

        if cwd == root and not cwd.exists():
            cwd.mkdir(parents=True, exist_ok=True)

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=os.environ.copy(),
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=max(timeout, 1))
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return f"Error: command timed out after {timeout} seconds"
        except Exception as exc:
            return f"Error executing command: {exc}"

        output = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace")
        if capture_stderr and err.strip():
            output = f"{output}\n[stderr]\n{err}" if output else f"[stderr]\n{err}"
        if process.returncode != 0:
            suffix = f"\nExit code: {process.returncode}"
            output = f"{output}{suffix}" if output else suffix.strip()
        if not output:
            output = "(no output)"
        if len(output) > 10_000:
            output = output[:10_000] + "\n... (truncated)"
        return output

    return [
        Tool(
            name="exec_command",
            description="Execute a shell command inside the configured allowed paths with timeout and safety checks.",
            parameters_schema_override={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute."},
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds.",
                        "default": default_timeout,
                    },
                    "working_dir": {
                        "type": "string",
                        "description": "Optional working directory. Relative paths resolve under the configured workspace.",
                    },
                    "capture_stderr": {
                        "type": "boolean",
                        "description": "Include stderr in the returned output.",
                        "default": True,
                    },
                },
                "required": ["command"],
            },
            handler=exec_command,
        )
    ]
