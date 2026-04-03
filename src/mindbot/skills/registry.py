"""In-memory registry for prompt-layer skills."""

from __future__ import annotations

from dataclasses import dataclass, field

from mindbot.skills.models import SkillDefinition, SkillSummary


@dataclass
class SkillRegistry:
    """Store and resolve loaded skills by name."""

    _skills: dict[str, SkillDefinition] = field(default_factory=dict)

    def register(self, skill: SkillDefinition, *, replace: bool = False) -> None:
        """Register a skill definition."""
        if skill.name in self._skills and not replace:
            raise ValueError(f"Skill '{skill.name}' is already registered")
        self._skills[skill.name] = skill

    def register_many(self, skills: list[SkillDefinition], *, replace: bool = False) -> None:
        """Register multiple skill definitions."""
        for skill in skills:
            self.register(skill, replace=replace)

    def get(self, name: str) -> SkillDefinition | None:
        """Return a registered skill by name."""
        return self._skills.get(name)

    def require(self, name: str) -> SkillDefinition:
        """Return a registered skill or raise."""
        skill = self.get(name)
        if skill is None:
            raise KeyError(f"Unknown skill: {name}")
        return skill

    def list_all(self) -> list[SkillDefinition]:
        """Return all skills in stable name order."""
        return [self._skills[name] for name in sorted(self._skills)]

    def list_summaries(self) -> list[SkillSummary]:
        """Return summaries for all registered skills."""
        return [skill.summary for skill in self.list_all()]

    def __contains__(self, name: str) -> bool:
        return name in self._skills

    def __len__(self) -> int:
        return len(self._skills)

    @classmethod
    def from_skills(cls, skills: list[SkillDefinition]) -> "SkillRegistry":
        """Construct a registry from a list of definitions."""
        registry = cls()
        registry.register_many(skills)
        return registry

