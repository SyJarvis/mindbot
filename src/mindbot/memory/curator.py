"""Rule-based memory curation for completed turns."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from mindbot.context.models import Message

MemoryCandidateKind = Literal["preference", "decision", "project_note", "fact"]


@dataclass(frozen=True)
class MemoryCandidate:
    """A curated memory candidate extracted from one completed turn."""

    content: str
    kind: MemoryCandidateKind
    importance: float
    metadata: dict[str, object] = field(default_factory=dict)


class MemoryCurator:
    """Extract long-lived memory candidates from a completed conversation turn."""

    _PREFERENCE_RE = re.compile(
        r"(我|本人|用户).{0,16}(喜欢|偏好|不喜欢|不想|希望以后|以后用|习惯|倾向)"
    )
    _DECISION_RE = re.compile(
        r"(决定|确定|以后按|约定|采用|改成|保持|不要再|优先)"
    )
    _PROJECT_RE = re.compile(
        r"(项目|配置|架构|接口|目录|路径|provider|模型|memory|tool|工具|示例|测试)"
    )
    _FACT_RE = re.compile(
        r"(我是|我在|我的|环境|系统|设备|使用的是|运行在)"
    )

    def __init__(self, *, min_importance: float = 0.65) -> None:
        self._min_importance = min_importance

    def curate_turn(
        self,
        *,
        user_text: str,
        assistant_text: str,
        trace: list["Message"] | None = None,
    ) -> list[MemoryCandidate]:
        """Return memory candidates worth storing for future sessions."""
        candidates: list[MemoryCandidate] = []
        source = user_text.strip()
        if not source:
            return []

        if self._PREFERENCE_RE.search(source):
            candidates.append(self._candidate("preference", source, 0.85))

        if self._DECISION_RE.search(source):
            candidates.append(self._candidate("decision", source, 0.8))

        if self._PROJECT_RE.search(source) and self._DECISION_RE.search(source):
            candidates.append(self._candidate("project_note", source, 0.78))

        if self._FACT_RE.search(source) and len(source) >= 8:
            candidates.append(self._candidate("fact", source, 0.72))

        if trace and _trace_has_side_effect(trace):
            summary = _summarize_tool_result(user_text, assistant_text)
            if summary:
                candidates.append(self._candidate("project_note", summary, 0.7))

        return _dedupe(
            candidate for candidate in candidates
            if candidate.importance >= self._min_importance
        )

    @staticmethod
    def _candidate(
        kind: MemoryCandidateKind,
        content: str,
        importance: float,
    ) -> MemoryCandidate:
        return MemoryCandidate(
            content=content,
            kind=kind,
            importance=importance,
            metadata={"source": "memory_curator", "kind": kind},
        )


def _trace_has_side_effect(trace: list["Message"]) -> bool:
    side_effect_tools = {
        "write_file",
        "edit_file",
        "delete_file",
        "run_shell",
        "execute_shell",
        "cron_add",
        "cron_update",
        "create_tool",
    }
    for msg in trace:
        if msg.tool_calls:
            if any(tc.name in side_effect_tools for tc in msg.tool_calls):
                return True
        if msg.role == "tool" and msg.tool_name in side_effect_tools:
            return True
    return False


def _summarize_tool_result(user_text: str, assistant_text: str) -> str:
    assistant = assistant_text.strip()
    if not assistant:
        return ""
    return f"Task result: {user_text.strip()} -> {assistant[:300]}"


def _dedupe(candidates) -> list[MemoryCandidate]:
    seen: set[tuple[str, str]] = set()
    result: list[MemoryCandidate] = []
    for candidate in candidates:
        key = (candidate.kind, candidate.content)
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result
