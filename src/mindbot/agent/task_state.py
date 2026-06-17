"""Session-scoped task intent and progress state."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

from mindbot.agent.models import StopReason

if TYPE_CHECKING:
    from mindbot.agent.models import AgentResponse


@dataclass
class TaskState:
    """Compact working state for the current session task."""

    goal: str = ""
    user_intent: str = ""
    current_plan: list[str] = field(default_factory=list)
    completed_steps: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    last_progress: str = ""
    needs_user_input: bool = False
    confidence: float = 0.5

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable snapshot."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "TaskState":
        """Build a TaskState from a persisted snapshot."""
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: value for key, value in data.items() if key in allowed})

    def before_turn(self, user_text: str) -> None:
        """Update goal and intent from the latest user message."""
        text = user_text.strip()
        if not text:
            return

        self.user_intent = text
        if not self.goal or _looks_like_new_goal(text):
            self.goal = text
            self.current_plan = []
            self.completed_steps = []
            self.blockers = []
            self.open_questions = []
            self.last_progress = ""
            self.needs_user_input = False
            self.confidence = 0.5

        if not self.current_plan:
            self.current_plan = ["Understand the request", "Execute the needed work", "Verify and report the result"]

    def after_turn(self, response: "AgentResponse") -> None:
        """Update progress from the completed turn response."""
        if response.stop_reason == StopReason.COMPLETED:
            self.needs_user_input = False
            self.confidence = min(1.0, self.confidence + 0.1)
            summary = _summarize_text(response.content)
            if summary:
                self.last_progress = summary
                _append_unique(self.completed_steps, summary, limit=8)
            return

        if response.stop_reason in {StopReason.USER_INPUT_NEEDED, StopReason.MAX_TURNS, StopReason.REPEATED_TOOL}:
            self.needs_user_input = True
            self.confidence = max(0.1, self.confidence - 0.1)
            blocker = response.content or response.stop_reason.value
            _append_unique(self.blockers, _summarize_text(blocker), limit=5)
            return

        if response.stop_reason == StopReason.ERROR:
            self.needs_user_input = True
            self.confidence = max(0.1, self.confidence - 0.2)
            _append_unique(self.blockers, "Last turn ended with an error.", limit=5)

    def render(self) -> str:
        """Render task state for the prompt's intent_state block."""
        if not self.goal and not self.user_intent:
            return ""

        lines = ["Current task state:"]
        if self.goal:
            lines.append(f"- Goal: {self.goal}")
        if self.user_intent:
            lines.append(f"- Latest user intent: {self.user_intent}")
        if self.current_plan:
            lines.append("- Current plan:")
            lines.extend(f"  {idx}. {step}" for idx, step in enumerate(self.current_plan, 1))
        if self.completed_steps:
            lines.append("- Completed:")
            lines.extend(f"  - {step}" for step in self.completed_steps[-5:])
        if self.blockers:
            lines.append("- Blockers:")
            lines.extend(f"  - {blocker}" for blocker in self.blockers[-3:])
        if self.open_questions:
            lines.append("- Open questions:")
            lines.extend(f"  - {question}" for question in self.open_questions[-3:])
        if self.last_progress:
            lines.append(f"- Last progress: {self.last_progress}")
        lines.append(f"- Needs user input: {'yes' if self.needs_user_input else 'no'}")
        lines.append(f"- Confidence: {self.confidence:.2f}")
        return "\n".join(lines)


def _looks_like_new_goal(text: str) -> bool:
    return bool(re.search(r"(开始|制定计划|实现|修复|添加|重构|排查|分析|设计|执行)", text))


def _summarize_text(text: str, limit: int = 160) -> str:
    cleaned = " ".join(text.strip().split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."


def _append_unique(items: list[str], item: str, *, limit: int) -> None:
    if not item or item in items:
        return
    items.append(item)
    del items[:-limit]
