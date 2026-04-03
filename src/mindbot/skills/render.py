"""Prompt rendering helpers for skills overview and detail blocks."""

from __future__ import annotations

from mindbot.skills.models import SkillDefinition, SkillSelection, SkillSummary
from mindbot.skills.registry import SkillRegistry


def render_skills_overview(summaries: list[SkillSummary]) -> str:
    """Render the lightweight overview block for visible skills."""
    if not summaries:
        return ""

    lines = ["Available skills:", ""]
    for summary in summaries:
        lines.append(f"- {summary.name}")
        if summary.when_to_use:
            lines.append(f"  - Use when: {summary.when_to_use}")
        if summary.description:
            lines.append(f"  - Description: {summary.description}")
        if summary.allowed_tools:
            lines.append(f"  - Allowed tools: {', '.join(summary.allowed_tools)}")
        if summary.loaded_from:
            lines.append(f"  - Source: {summary.loaded_from}")
        lines.append("")
    return "\n".join(lines).strip()


def render_skills_detail(
    selections: list[SkillSelection],
    registry: SkillRegistry | None,
) -> str:
    """Render selected skill bodies with per-skill rationale."""
    if not selections or registry is None:
        return ""

    sections: list[str] = []
    for selection in selections:
        skill: SkillDefinition | None = registry.get(selection.skill_name)
        if skill is None:
            continue
        section = [
            f"Selected skill: {skill.name}",
            "",
            "Why selected:",
            f"- {selection.reason}",
            "",
            "Skill instructions:",
            skill.body.strip(),
        ]
        sections.append("\n".join(section).strip())
    return "\n\n".join(section for section in sections if section).strip()

