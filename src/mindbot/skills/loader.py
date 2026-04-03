"""Discovery and parsing for ``SKILL.md`` packages."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mindbot.skills.models import SkillDefinition
from mindbot.skills.registry import SkillRegistry


@dataclass(frozen=True)
class SkillRoot:
    """A filesystem root that contains skill package directories."""

    path: Path
    loaded_from: str


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


def parse_skill_markdown(path: Path, *, loaded_from: str) -> SkillDefinition:
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
        """Return the user root plus optional configured roots."""
        user_root = Path.home() / ".mindbot" / "skills"
        roots = [
            SkillRoot(path=user_root, loaded_from="user"),
        ]
        for entry in configured_dirs or []:
            path = Path(entry).expanduser()
            roots.append(SkillRoot(path=path, loaded_from="configured"))
        return roots

    def scan(self) -> list[SkillDefinition]:
        """Load all skills from configured roots."""
        loaded: list[SkillDefinition] = []
        seen_paths: set[Path] = set()

        for root in self._roots:
            root_path = root.path.expanduser()
            if not root_path.exists() or not root_path.is_dir():
                continue
            for skill_path in sorted(root_path.glob("*/SKILL.md")):
                resolved = skill_path.resolve()
                if resolved in seen_paths:
                    continue
                seen_paths.add(resolved)
                loaded.append(parse_skill_markdown(skill_path, loaded_from=root.loaded_from))
        return loaded

    def load_registry(self) -> SkillRegistry:
        """Load all discovered skills into a registry."""
        registry = SkillRegistry()
        for skill in self.scan():
            registry.register(skill, replace=True)
        return registry

