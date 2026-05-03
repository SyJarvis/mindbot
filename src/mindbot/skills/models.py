"""Runtime models for prompt-layer skills."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


SkillLoadMode = Literal["overview", "detail"]
SkillScope = Literal["builtin", "user", "project", "extra"]
ScriptLanguage = Literal["python", "bash", "sh", "node", "ruby", "perl", ""]


def _detect_language(path: Path) -> str:
    """Detect script language from file extension."""
    suffix = path.suffix.lower()
    mapping = {
        ".py": "python",
        ".sh": "bash",
        ".bash": "bash",
        ".js": "node",
        ".rb": "ruby",
        ".pl": "perl",
    }
    return mapping.get(suffix, "")


def _build_entrypoint(path: Path) -> str:
    """Build execution entrypoint for a script."""
    suffix = path.suffix.lower()
    mapping = {
        ".py": "python {path}",
        ".sh": "bash {path}",
        ".bash": "bash {path}",
        ".js": "node {path}",
        ".rb": "ruby {path}",
        ".pl": "perl {path}",
    }
    return mapping.get(suffix, "{path}")


@dataclass(frozen=True)
class ScriptDefinition:
    """Definition of an executable script bundled with a skill."""

    name: str
    path: Path
    description: str = ""
    language: str = ""
    entrypoint: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path):
            object.__setattr__(self, "path", Path(self.path))

    @classmethod
    def from_file(cls, path: Path, description: str = "") -> "ScriptDefinition":
        """Create a ScriptDefinition from a script file path."""
        return cls(
            name=path.stem,
            path=path,
            description=description,
            language=_detect_language(path),
            entrypoint=_build_entrypoint(path),
        )

    @property
    def command(self) -> str:
        """Get the full command to execute this script."""
        return self.entrypoint.format(path=str(self.path))


@dataclass(frozen=True)
class SkillDefinition:
    """Full parsed representation of a ``SKILL.md`` package."""

    name: str
    description: str = ""
    when_to_use: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    user_invocable: bool | None = None
    disable_model_invocation: bool | None = None
    context: dict[str, Any] = field(default_factory=dict)
    agent: str | None = None
    paths: list[str] = field(default_factory=list)
    loaded_from: str = ""
    scope: SkillScope = "user"
    skill_dir: Path = field(default_factory=Path)
    body: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    scripts: list[ScriptDefinition] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("SkillDefinition.name must not be empty")
        if not isinstance(self.skill_dir, Path):
            object.__setattr__(self, "skill_dir", Path(self.skill_dir))

    @property
    def summary(self) -> "SkillSummary":
        """Return the prompt-safe summary view for this skill."""
        return SkillSummary(
            name=self.name,
            description=self.description,
            when_to_use=self.when_to_use,
            allowed_tools=list(self.allowed_tools),
            loaded_from=self.loaded_from,
            scope=self.scope,
        )

    @property
    def metadata_text(self) -> str:
        """Flatten user-visible metadata for simple text matching."""
        parts = [
            self.name,
            self.description,
            self.when_to_use,
            " ".join(self.allowed_tools),
            " ".join(self.paths),
            " ".join(s.name for s in self.scripts),
        ]
        return " ".join(part for part in parts if part).strip().lower()

    def get_script(self, name: str) -> ScriptDefinition | None:
        """Get a script by name."""
        for script in self.scripts:
            if script.name == name:
                return script
        return None


@dataclass(frozen=True)
class SkillSummary:
    """Minimal prompt representation for overview injection."""

    name: str
    description: str = ""
    when_to_use: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    loaded_from: str = ""
    scope: SkillScope = "user"


@dataclass(frozen=True)
class SkillSelection:
    """Result of selecting a skill for one turn."""

    skill_name: str
    reason: str
    load_mode: SkillLoadMode
    score: int = 0

