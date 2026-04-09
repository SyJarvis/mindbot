"""MindBot-specific runtime inspection tools."""

from __future__ import annotations

import json
import os
import platform
import shutil
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mindbot.capability.backends.tooling.models import Tool
from mindbot.config.loader import load_config
from mindbot.skills import SkillLoader
from mindbot.tools.path_policy import resolve_allowed_roots


def _path_info(path: Path) -> dict[str, Any]:
    expanded = path.expanduser()
    exists = expanded.exists()
    info: dict[str, Any] = {
        "path": str(expanded),
        "exists": exists,
        "is_file": expanded.is_file() if exists else False,
        "is_dir": expanded.is_dir() if exists else False,
    }
    if exists and expanded.is_file():
        info["size_bytes"] = expanded.stat().st_size
    return info


def _count_files(path: Path) -> int:
    expanded = path.expanduser()
    if not expanded.exists() or not expanded.is_dir():
        return 0
    return sum(1 for entry in expanded.rglob("*") if entry.is_file())


def _latest_mtime(path: Path) -> str | None:
    expanded = path.expanduser()
    if not expanded.exists() or not expanded.is_dir():
        return None
    latest = max(
        (entry.stat().st_mtime for entry in expanded.rglob("*") if entry.is_file()),
        default=None,
    )
    if latest is None:
        return None
    return datetime.fromtimestamp(latest, tz=timezone.utc).isoformat()


def _discover_config_paths(workspace: Path) -> list[Path]:
    paths: list[Path] = []
    global_path = Path.home() / ".mindbot" / "settings.json"
    if global_path.exists():
        paths.append(global_path)

    env_path = os.environ.get("MIND_CONFIG_PATH")
    if env_path:
        candidate = Path(env_path).expanduser()
        if candidate.exists() and candidate not in paths:
            paths.append(candidate)

    local_path = workspace / ".mindbot" / "settings.json"
    if local_path.exists() and local_path not in paths:
        paths.append(local_path)

    return paths


def _memory_available_bytes() -> int | None:
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                parts = line.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    return int(parts[1]) * 1024
    return None


def _memory_total_bytes() -> int | None:
    if hasattr(os, "sysconf") and "SC_PAGE_SIZE" in os.sysconf_names and "SC_PHYS_PAGES" in os.sysconf_names:
        try:
            page_size = int(os.sysconf("SC_PAGE_SIZE"))
            page_count = int(os.sysconf("SC_PHYS_PAGES"))
            return page_size * page_count
        except (OSError, ValueError):
            return None
    return None


def create_mindbot_tools(
    workspace: Path | str,
    *,
    restrict_to_workspace: bool = True,
    allowed_paths: Sequence[Path | str] | None = None,
    session_cwd: Path | str | None = None,
    effective_workspace: Path | str | None = None,
    session_trusted_paths: Sequence[Path | str] | None = None,
    session_cwd_authorized: bool | None = None,
) -> list[Tool]:
    """Create MindBot-specific built-in inspection tools."""
    root, allowed_roots = resolve_allowed_roots(
        workspace,
        restrict_to_workspace=restrict_to_workspace,
        allowed_paths=allowed_paths,
    )

    def get_mindbot_runtime_info() -> str:
        """Return basic MindBot runtime, config, skills, memory, and system info as JSON."""
        home_root = Path.home() / ".mindbot"
        config_paths = _discover_config_paths(root)

        config_error: str | None = None
        try:
            config = load_config(project_dir=root, missing_env="empty")
        except Exception as exc:
            config = None
            config_error = f"{type(exc).__name__}: {exc}"

        skills_payload: dict[str, Any] = {
            "loaded_skill_count": 0,
            "loaded_skill_names": [],
        }
        if config is not None:
            registry = SkillLoader(
                SkillLoader.default_roots(config.skills.skill_dirs)
            ).load_registry()
            skills_payload = {
                "enabled": config.skills.enabled,
                "loaded_skill_count": len(registry),
                "loaded_skill_names": [skill.name for skill in registry.list_all()],
                "always_include": list(config.skills.always_include),
                "skill_dirs": [str(Path(path).expanduser()) for path in config.skills.skill_dirs],
                "max_visible": config.skills.max_visible,
                "max_detail_load": config.skills.max_detail_load,
                "trigger_mode": config.skills.trigger_mode,
            }

        memory_payload: dict[str, Any] = {}
        journal_payload: dict[str, Any] = {}
        config_payload: dict[str, Any] = {
            "discovered_config_paths": [str(path) for path in config_paths],
            "config_error": config_error,
            "mindbot_home": str(home_root),
            "system_prompt_file": _path_info(home_root / "SYSTEM.md"),
            "history_dir": {
                **_path_info(home_root / "history"),
                "file_count": _count_files(home_root / "history"),
            },
        }
        if config is not None:
            memory_db = Path(config.memory.storage_path).expanduser()
            memory_md = Path(config.memory.markdown_path).expanduser()
            journal_dir = Path(config.session_journal.path).expanduser()
            config_payload.update(
                {
                    "agent_model": config.agent.model,
                    "configured_workspace": str(Path(config.agent.workspace).expanduser()),
                    "system_path_whitelist": [
                        str(Path(path).expanduser()) for path in config.agent.system_path_whitelist
                    ],
                    "trusted_paths": [
                        str(Path(path).expanduser()) for path in config.agent.trusted_paths
                    ],
                    "restrict_to_workspace": config.agent.restrict_to_workspace,
                    "shell_execution": {
                        "policy": config.agent.shell_execution.policy.value,
                        "sandbox_provider": config.agent.shell_execution.sandbox_provider.value,
                        "fail_if_unavailable": config.agent.shell_execution.fail_if_unavailable,
                    },
                    "provider_instances": [
                        {"name": name, "type": provider.type}
                        for name, provider in config.providers.items()
                    ],
                    "settings_file": _path_info(config_paths[-1]) if config_paths else _path_info(home_root / "settings.json"),
                }
            )
            memory_payload = {
                "storage": _path_info(memory_db),
                "markdown": {
                    **_path_info(memory_md),
                    "file_count": _count_files(memory_md),
                    "short_term_retention_days": config.memory.short_term_retention_days,
                    "enable_fts": config.memory.enable_fts,
                },
            }
            journal_payload = {
                "enabled": config.session_journal.enabled,
                "path": str(journal_dir),
                "exists": journal_dir.exists(),
                "file_count": _count_files(journal_dir),
                "latest_modified_at": _latest_mtime(journal_dir),
            }

        disk = shutil.disk_usage(root)
        payload = {
            "config": config_payload,
            "memory": memory_payload,
            "journal": journal_payload,
            "skills": skills_payload,
            "system": {
                "platform": platform.platform(),
                "python_version": platform.python_version(),
                "workspace": str(root),
                "effective_workspace": (
                    str(Path(effective_workspace).expanduser().resolve())
                    if effective_workspace is not None
                    else str(root)
                ),
                "session_cwd": (
                    str(Path(session_cwd).expanduser().resolve())
                    if session_cwd is not None
                    else None
                ),
                "session_cwd_authorized": session_cwd_authorized,
                "session_trusted_paths": [
                    str(Path(path).expanduser().resolve()) for path in (session_trusted_paths or [])
                ],
                "allowed_paths": [str(path) for path in allowed_roots],
                "allowed_path_policy": "Each allowed path grants access to that directory tree.",
                "shell_execution_boundary": (
                    "cwd_guard validates the launch directory and dangerous command patterns, "
                    "but does not provide OS-level shell sandboxing."
                ),
                "cpu_count": os.cpu_count(),
                "memory_total_bytes": _memory_total_bytes(),
                "memory_available_bytes": _memory_available_bytes(),
                "disk_total_bytes": disk.total,
                "disk_free_bytes": disk.free,
            },
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    return [
        Tool(
            name="get_mindbot_runtime_info",
            description=(
                "Return structured runtime information about MindBot, including config, "
                "memory, journal, loaded skills, basic system resources, and allowed path roots."
            ),
            parameters_schema_override={
                "type": "object",
                "properties": {},
            },
            handler=get_mindbot_runtime_info,
        )
    ]

