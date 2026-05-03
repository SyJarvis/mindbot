"""Discovery and parsing for ``SKILL.md`` packages."""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mindbot.skills.models import ScriptDefinition, SkillDefinition, SkillScope
from mindbot.skills.registry import SkillRegistry


@dataclass(frozen=True)
class SkillRoot:
    """A filesystem root that contains skill package directories."""

    path: Path
    loaded_from: str
    scope: SkillScope = "user"
    priority: int = 0


def _coerce_scalar(value: str) -> Any:
    text = value.strip()
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none"}:
        return None
    if not text:
        return ""
    if text[0] in {'"', "'", "[", "{", "("}:
        try:
            return ast.literal_eval(text)
        except (ValueError, SyntaxError):
            return text.strip("'\"")
    if text.isdigit():
        return int(text)
    return text


def _parse_frontmatter_block(frontmatter: str) -> dict[str, Any]:
    """Parse a conservative subset of YAML frontmatter."""
    parsed: dict[str, Any] = {}
    current_key: str | None = None
    current_list: list[Any] | None = None

    for raw_line in frontmatter.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if line.startswith("  - ") and current_key is not None and current_list is not None:
            current_list.append(_coerce_scalar(line[4:]))
            continue

        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()

        if not value:
            parsed[key] = []
            current_key = key
            current_list = parsed[key]
            continue

        parsed[key] = _coerce_scalar(value)
        current_key = None
        current_list = None

    return parsed


def _discover_scripts(skill_dir: Path) -> list[ScriptDefinition]:
    """Discover executable scripts in a skill's scripts/ directory."""
    scripts_dir = skill_dir / "scripts"
    if not scripts_dir.exists() or not scripts_dir.is_dir():
        return []

    scripts: list[ScriptDefinition] = []
    for entry in sorted(scripts_dir.iterdir()):
        if not entry.is_file():
            continue
        # Skip hidden files and non-executable files
        if entry.name.startswith("."):
            continue
        # Check if file is executable or has a recognized script extension
        is_executable = os.access(entry, os.X_OK)
        has_script_ext = entry.suffix.lower() in {".py", ".sh", ".bash", ".js", ".rb", ".pl"}
        if is_executable or has_script_ext:
            scripts.append(ScriptDefinition.from_file(entry))
    return scripts


def parse_skill_markdown(path: Path, *, loaded_from: str, scope: SkillScope = "user") -> SkillDefinition:
    """Parse a ``SKILL.md`` file into a :class:`SkillDefinition`."""
    text = path.read_text(encoding="utf-8")
    frontmatter: dict[str, Any] = {}
    body = text.strip()

    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            frontmatter = _parse_frontmatter_block(text[4:end])
            body = text[end + 4 :].lstrip("\n")

    name = str(frontmatter.get("name") or path.parent.name).strip()
    description = str(frontmatter.get("description") or "").strip()
    when_to_use = str(
        frontmatter.get("when_to_use")
        or frontmatter.get("use_when")
        or frontmatter.get("trigger")
        or ""
    ).strip()

    allowed_tools = frontmatter.get("allowed_tools") or []
    if not isinstance(allowed_tools, list):
        allowed_tools = [str(allowed_tools)]

    paths = frontmatter.get("paths") or []
    if not isinstance(paths, list):
        paths = [str(paths)]

    context = frontmatter.get("context") or {}
    if not isinstance(context, dict):
        context = {"value": context}

    dependency = frontmatter.get("dependency")
    metadata = dict(frontmatter)
    if dependency is not None and "dependency" not in metadata:
        metadata["dependency"] = dependency

    # Discover bundled scripts
    scripts = _discover_scripts(path.parent)

    return SkillDefinition(
        name=name,
        description=description,
        when_to_use=when_to_use,
        allowed_tools=[str(item) for item in allowed_tools],
        user_invocable=frontmatter.get("user_invocable"),
        disable_model_invocation=frontmatter.get("disable_model_invocation"),
        context=context,
        agent=str(frontmatter["agent"]) if frontmatter.get("agent") is not None else None,
        paths=[str(item) for item in paths],
        loaded_from=loaded_from,
        scope=scope,
        skill_dir=path.parent,
        body=body.strip(),
        metadata=metadata,
        scripts=scripts,
    )


def _strip_md_suffix(filename: str) -> str:
    """Return *filename* without a trailing ``.md`` (case-insensitive)."""
    if filename.lower().endswith(".md"):
        return filename[:-len(".md")]
    return filename


def parse_flat_skill_markdown(
    path: Path,
    *,
    loaded_from: str,
    scope: SkillScope = "user",
) -> SkillDefinition:
    """Parse a flat ``.md`` skill file into a :class:`SkillDefinition`.

    Flat skills use the filename stem as the default name instead of the
    parent directory name.
    """
    text = path.read_text(encoding="utf-8")
    frontmatter: dict[str, Any] = {}
    body = text.strip()

    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            frontmatter = _parse_frontmatter_block(text[4:end])
            body = text[end + 4 :].lstrip("\n")

    # Use filename stem as default name for flat skills
    default_name = _strip_md_suffix(path.name)
    name = str(frontmatter.get("name") or default_name).strip()
    description = str(frontmatter.get("description") or "").strip()
    when_to_use = str(
        frontmatter.get("when_to_use")
        or frontmatter.get("use_when")
        or frontmatter.get("trigger")
        or ""
    ).strip()

    allowed_tools = frontmatter.get("allowed_tools") or []
    if not isinstance(allowed_tools, list):
        allowed_tools = [str(allowed_tools)]

    paths = frontmatter.get("paths") or []
    if not isinstance(paths, list):
        paths = [str(paths)]

    context = frontmatter.get("context") or {}
    if not isinstance(context, dict):
        context = {"value": context}

    dependency = frontmatter.get("dependency")
    metadata = dict(frontmatter)
    if dependency is not None and "dependency" not in metadata:
        metadata["dependency"] = dependency

    return SkillDefinition(
        name=name,
        description=description,
        when_to_use=when_to_use,
        allowed_tools=[str(item) for item in allowed_tools],
        user_invocable=frontmatter.get("user_invocable"),
        disable_model_invocation=frontmatter.get("disable_model_invocation"),
        context=context,
        agent=str(frontmatter["agent"]) if frontmatter.get("agent") is not None else None,
        paths=[str(item) for item in paths],
        loaded_from=loaded_from,
        scope=scope,
        skill_dir=path.parent,
        body=body.strip(),
        metadata=metadata,
    )


class SkillLoader:
    """Load skills from a list of configured roots."""

    def __init__(self, roots: list[SkillRoot]) -> None:
        self._roots = roots

    @classmethod
    def default_roots(cls, configured_dirs: list[str] | None = None) -> list[SkillRoot]:
        """Return default skill roots with scope and priority.

        Priority order (highest first):
        1. project: .agents/skills (110)
        2. user: ~/.config/agents/skills (100)
        3. user: ~/.mindbot/skills (90)
        4. configured: user-specified dirs (80)
        """
        roots: list[SkillRoot] = []

        # Project-level skills (highest priority, resolved lazily by work_dir)
        # Note: project roots need work_dir, added by caller if needed

        # User-level skills
        roots.append(SkillRoot(
            path=Path.home() / ".config" / "agents" / "skills",
            loaded_from="user",
            scope="user",
            priority=100,
        ))
        roots.append(SkillRoot(
            path=Path.home() / ".mindbot" / "skills",
            loaded_from="user",
            scope="user",
            priority=90,
        ))

        # Configured directories
        for entry in configured_dirs or []:
            path = Path(entry).expanduser()
            roots.append(SkillRoot(
                path=path,
                loaded_from="configured",
                scope="extra",
                priority=80,
            ))

        return roots

    @classmethod
    def with_project_root(cls, work_dir: Path, configured_dirs: list[str] | None = None) -> list[SkillRoot]:
        """Return roots including project-level skills.

        Args:
            work_dir: Current working directory for project skill discovery.
            configured_dirs: Additional skill directories from config.
        """
        roots: list[SkillRoot] = []

        # Project-level skills (highest priority)
        roots.append(SkillRoot(
            path=work_dir / ".agents" / "skills",
            loaded_from="project",
            scope="project",
            priority=110,
        ))

        # User-level skills
        roots.append(SkillRoot(
            path=Path.home() / ".config" / "agents" / "skills",
            loaded_from="user",
            scope="user",
            priority=100,
        ))
        roots.append(SkillRoot(
            path=Path.home() / ".mindbot" / "skills",
            loaded_from="user",
            scope="user",
            priority=90,
        ))

        # Configured directories
        for entry in configured_dirs or []:
            path = Path(entry).expanduser()
            roots.append(SkillRoot(
                path=path,
                loaded_from="configured",
                scope="extra",
                priority=80,
            ))

        return roots

    def scan(self) -> list[SkillDefinition]:
        """Load all skills from configured roots.

        Supports two layouts:
        1. Subdirectory: ``<skills_dir>/<name>/SKILL.md`` (canonical, higher priority)
        2. Flat: ``<skills_dir>/<name>.md`` (compatible, lower priority)

        Skills are deduplicated by name (case-insensitive):
        - Higher priority roots win over lower priority ones
        - When priority is equal, later roots override earlier ones (last wins)
        - Subdirectory form wins over flat form within the same root
        """
        # Group roots by priority
        by_priority: dict[int, list[SkillRoot]] = {}
        for root in self._roots:
            by_priority.setdefault(root.priority, []).append(root)

        # Process priorities from highest to lowest
        seen_names: dict[str, SkillDefinition] = {}
        loaded: list[SkillDefinition] = []

        for priority in sorted(by_priority.keys(), reverse=True):
            roots_at_priority = by_priority[priority]

            # Within same priority, process in order (last wins for same priority)
            for root in roots_at_priority:
                root_path = root.path.expanduser()
                if not root_path.exists() or not root_path.is_dir():
                    continue

                # Pass 1: subdirectory form (canonical, higher priority)
                for skill_path in sorted(root_path.glob("*/SKILL.md")):
                    try:
                        skill = parse_skill_markdown(
                            skill_path,
                            loaded_from=root.loaded_from,
                            scope=root.scope,
                        )
                    except Exception:
                        continue

                    normalized_name = skill.name.lower()
                    if normalized_name not in seen_names:
                        seen_names[normalized_name] = skill
                        loaded.append(skill)
                    else:
                        existing = seen_names[normalized_name]
                        existing_root = next(
                            (r for r in self._roots if r.loaded_from == existing.loaded_from),
                            None,
                        )
                        if existing_root and existing_root.priority <= priority:
                            idx = loaded.index(existing)
                            loaded[idx] = skill
                            seen_names[normalized_name] = skill

                # Pass 2: flat .md form (compatible, skipped if subdir exists)
                for md_path in sorted(root_path.glob("*.md")):
                    # Skip top-level SKILL.md marker file
                    if md_path.name.upper() == "SKILL.MD":
                        continue

                    try:
                        skill = parse_flat_skill_markdown(
                            md_path,
                            loaded_from=root.loaded_from,
                            scope=root.scope,
                        )
                    except Exception:
                        continue

                    normalized_name = skill.name.lower()
                    if normalized_name not in seen_names:
                        seen_names[normalized_name] = skill
                        loaded.append(skill)
                    # Note: flat form does not override subdirectory form
                    # (subdir was processed first in Pass 1)

        return loaded

    def load_registry(self) -> SkillRegistry:
        """Load all discovered skills into a registry."""
        registry = SkillRegistry()
        for skill in self.scan():
            registry.register(skill, replace=True)
        return registry

