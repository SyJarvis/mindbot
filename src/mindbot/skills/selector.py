"""Selection logic for prompt-layer skills."""

from __future__ import annotations

import re
from dataclasses import dataclass

from mindbot.skills.models import SkillDefinition, SkillSelection, SkillSummary
from mindbot.skills.registry import SkillRegistry

_TOKEN_RE = re.compile(r"[A-Za-z0-9_\-]+|[\u4e00-\u9fff]{2,}")


def _tokenize(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN_RE.findall(text.lower())]


@dataclass(frozen=True)
class SkillSelectionResult:
    """Final overview/detail selection for one turn."""

    summaries: list[SkillSummary]
    selections: list[SkillSelection]


class SkillSelector:
    """Select relevant skills for one turn using lightweight metadata matching."""

    def __init__(
        self,
        registry: SkillRegistry | None,
        *,
        enabled: bool = True,
        always_include: list[str] | None = None,
        max_visible: int = 8,
        max_detail_load: int = 2,
        trigger_mode: str = "metadata-match",
    ) -> None:
        self._registry = registry
        self._enabled = enabled
        self._always_include = always_include or []
        self._max_visible = max_visible
        self._max_detail_load = max_detail_load
        self._trigger_mode = trigger_mode

    def select(self, query: str) -> SkillSelectionResult:
        """Return overview summaries plus detail selections for *query*."""
        if not self._enabled or self._registry is None or len(self._registry) == 0:
            return SkillSelectionResult(summaries=[], selections=[])

        query_text = query.strip().lower()
        query_tokens = _tokenize(query_text)

        scored: list[tuple[SkillDefinition, int, str]] = []
        for skill in self._registry.list_all():
            score, reason = self._score_skill(skill, query_text, query_tokens)
            if score > 0:
                scored.append((skill, score, reason))

        scored.sort(key=lambda item: (-item[1], item[0].name))

        overview_names: list[str] = []
        for skill_name in self._always_include:
            if skill_name in self._registry and skill_name not in overview_names:
                overview_names.append(skill_name)
        for skill, _, _ in scored:
            if skill.name not in overview_names:
                overview_names.append(skill.name)
            if len(overview_names) >= self._max_visible:
                break

        if not overview_names:
            overview_names = [skill.name for skill in self._registry.list_all()[: self._max_visible]]

        summaries = [self._registry.require(name).summary for name in overview_names[: self._max_visible]]

        selections = [
            SkillSelection(
                skill_name=skill.name,
                reason=reason,
                load_mode="detail",
                score=score,
            )
            for skill, score, reason in scored[: self._max_detail_load]
        ]
        return SkillSelectionResult(summaries=summaries, selections=selections)

    def _score_skill(
        self,
        skill: SkillDefinition,
        query_text: str,
        query_tokens: list[str],
    ) -> tuple[int, str]:
        name_match = skill.name.lower() in query_text
        metadata_text = skill.metadata_text

        if self._trigger_mode == "explicit-only":
            if name_match:
                return 100, f"Query explicitly referenced skill `{skill.name}`."
            return 0, ""

        score = 0
        matched_tokens: list[str] = []
        if name_match:
            score += 100
            matched_tokens.append(skill.name)

        for token in query_tokens:
            if len(token) < 2:
                continue
            if token in metadata_text:
                score += 10
                matched_tokens.append(token)

        if self._trigger_mode == "hybrid" and not (name_match or matched_tokens):
            return 0, ""
        if self._trigger_mode not in {"metadata-match", "hybrid", "explicit-only"}:
            return 0, ""
        if score == 0:
            return 0, ""

        unique_tokens = ", ".join(dict.fromkeys(matched_tokens).keys())
        if name_match:
            reason = f"Query referenced `{skill.name}` and matched skill metadata."
        else:
            reason = f"Query matched skill metadata: {unique_tokens}."
        return score, reason

