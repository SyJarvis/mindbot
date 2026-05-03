"""Skill script execution tools."""

from __future__ import annotations

import asyncio
from pathlib import Path

from mindbot.capability.backends.tooling.models import Tool
from mindbot.skills.models import ScriptDefinition
from mindbot.skills.registry import SkillRegistry
from mindbot.tools.path_policy import is_within_allowed_roots, resolve_allowed_roots


class SkillScriptError(Exception):
    """Error executing a skill script."""


def create_skill_script_tools(
    workspace: Path | str,
    skill_registry: SkillRegistry | None,
    *,
    restrict_to_workspace: bool = True,
    allowed_paths: list[Path | str] | None = None,
    allowlist: list[str] | None = None,
    max_timeout: int = 60,
) -> list[Tool]:
    """Create skill script execution tools.

    Args:
        workspace: Base workspace directory.
        skill_registry: Registry containing loaded skills.
        restrict_to_workspace: Whether to restrict script execution to workspace.
        allowed_paths: Additional allowed paths for script execution.
        allowlist: List of allowed scripts in format "skill_name:script_name".
                   If None or empty, all scripts are allowed.
        max_timeout: Maximum execution timeout in seconds.
    """
    if skill_registry is None:
        return []

    root, allowed_roots = resolve_allowed_roots(
        workspace,
        restrict_to_workspace=restrict_to_workspace,
        allowed_paths=allowed_paths,
    )

    def _is_allowed(skill_name: str, script_name: str) -> bool:
        """Check if a script is in the allowlist."""
        if not allowlist:
            return True
        full_name = f"{skill_name}:{script_name}"
        return full_name in allowlist or f"{skill_name}:*" in allowlist

    def _validate_script_path(script: ScriptDefinition, skill_dir: Path) -> str | None:
        """Validate script path is within allowed roots."""
        try:
            resolved = script.path.resolve()
            if not is_within_allowed_roots(resolved, allowed_roots):
                return (
                    f"Error: script path outside allowed roots: {script.path} "
                    f"(allowed: {', '.join(str(p) for p in allowed_roots)})"
                )
            # Also ensure script is within the skill directory
            if not str(resolved).startswith(str(skill_dir.resolve())):
                return f"Error: script must be within skill directory: {script.path}"
        except OSError as exc:
            return f"Error: invalid script path: {exc}"
        return None

    async def execute_skill_script(
        skill_name: str,
        script_name: str,
        args: str = "",
        timeout: int = 30,
    ) -> str:
        """Execute a script bundled with a skill.

        Args:
            skill_name: Name of the skill containing the script.
            script_name: Name of the script to execute (without extension).
            args: Space-separated arguments to pass to the script.
            timeout: Execution timeout in seconds (max {max_timeout}).

        Returns:
            Script output (stdout) or error message.
        """
        # Validate skill exists
        skill = skill_registry.get(skill_name)
        if skill is None:
            available = [s.name for s in skill_registry.list_all()]
            return f"Error: skill '{skill_name}' not found. Available: {available}"

        # Validate script exists
        script = skill.get_script(script_name)
        if script is None:
            available = [s.name for s in skill.scripts]
            return (
                f"Error: script '{script_name}' not found in skill '{skill_name}'. "
                f"Available: {available}"
            )

        # Check allowlist
        if not _is_allowed(skill_name, script_name):
            return (
                f"Error: script '{skill_name}:{script_name}' is not in the allowlist. "
                f"Configure skills.scripts.allowlist to enable it."
            )

        # Validate path
        path_error = _validate_script_path(script, skill.skill_dir)
        if path_error:
            return path_error

        # Clamp timeout
        timeout = min(max(1, timeout), max_timeout)

        # Build command
        cmd = script.command
        if args:
            cmd = f"{cmd} {args}"

        # Execute
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=skill.skill_dir,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return f"Error: script execution timed out after {timeout}s"

            output = stdout.decode(errors="replace").strip()
            error_output = stderr.decode(errors="replace").strip()

            if proc.returncode != 0:
                result = f"Script exited with code {proc.returncode}"
                if error_output:
                    result += f"\n\nStderr:\n{error_output}"
                if output:
                    result += f"\n\nStdout:\n{output}"
                return result

            if not output:
                return "(script produced no output)"

            return output

        except Exception as exc:
            return f"Error: failed to execute script: {exc}"

    async def list_skill_scripts(skill_name: str = "") -> str:
        """List available scripts for a skill or all skills.

        Args:
            skill_name: Name of the skill to list scripts for. If empty, lists all.

        Returns:
            Formatted list of available scripts.
        """
        if skill_name:
            skill = skill_registry.get(skill_name)
            if skill is None:
                return f"Error: skill '{skill_name}' not found"
            skills = [skill]
        else:
            skills = skill_registry.list_all()

        lines: list[str] = []
        for skill in skills:
            if not skill.scripts:
                continue
            lines.append(f"## {skill.name}")
            for script in skill.scripts:
                status = "allowed" if _is_allowed(skill.name, script.name) else "blocked"
                lines.append(f"  - {script.name} ({script.language or 'unknown'}) [{status}]")
                if script.description:
                    lines.append(f"    Description: {script.description}")
            lines.append("")

        if not lines:
            return "No scripts found."
        return "\n".join(lines)

    return [
        Tool(
            name="execute_skill_script",
            description=(
                "Execute a script bundled with a skill. Scripts provide deterministic, "
                "reusable operations that can be run instead of generating code. "
                f"Maximum timeout: {max_timeout}s."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "Name of the skill containing the script",
                    },
                    "script_name": {
                        "type": "string",
                        "description": "Name of the script to execute (without extension)",
                    },
                    "args": {
                        "type": "string",
                        "description": "Space-separated arguments to pass to the script",
                        "default": "",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Execution timeout in seconds",
                        "default": 30,
                        "minimum": 1,
                        "maximum": max_timeout,
                    },
                },
                "required": ["skill_name", "script_name"],
            },
            handler=execute_skill_script,
        ),
        Tool(
            name="list_skill_scripts",
            description="List available scripts for skills. Shows script names, languages, and allowlist status.",
            parameters={
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "Name of the skill to list scripts for. Empty for all skills.",
                        "default": "",
                    },
                },
                "required": [],
            },
            handler=list_skill_scripts,
        ),
    ]
