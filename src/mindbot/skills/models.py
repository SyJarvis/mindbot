"""Runtime models for prompt-layer skills."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


SkillLoadMode = Literal["overview", "detail"]


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
    skill_dir: Path = field(default_factory=Path)
    body: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

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
        ]
        return " ".join(part for part in parts if part).strip().lower()


@dataclass(frozen=True)
class SkillSummary:
    """Minimal prompt representation for overview injection."""

    name: str
    description: str = ""
    when_to_use: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    loaded_from: str = ""


@dataclass(frozen=True)
class SkillSelection:
    """Result of selecting a skill for one turn."""

    skill_name: str
    reason: str
    load_mode: SkillLoadMode
    score: int = 0

