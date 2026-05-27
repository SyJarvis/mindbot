"""Conversation continuity snapshot.

A :class:`ConversationContinuitySnapshot` captures the structured state
of an ongoing conversation so the LLM maintains context across compressed
or truncated dialogue history.  It is updated incrementally after each
turn and injected as a high-priority :class:`~mindbot.context.items.ContextItem`.

The snapshot has explicit sections for task, decisions, focus, open
questions, likely actions, and deictic reference bindings.  This
addresses the core Phase A problem: when history is compressed, the LLM
can still resolve "this", "next step", and other referring expressions
because the snapshot records what those expressions point to.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from mindbot.context.models import Message
from mindbot.logging import logger

if TYPE_CHECKING:
    from mindbot.providers.adapter import ProviderAdapter


@dataclass
class ConversationContinuitySnapshot:
    """Structured continuity state for a multi-turn conversation."""

    current_task: str = ""
    confirmed_decisions: list[str] = field(default_factory=list)
    current_focus: str = ""
    open_questions: list[str] = field(default_factory=list)
    next_likely_action: str = ""
    reference_bindings: dict[str, str] = field(default_factory=dict)
    updated_at: float = 0.0

    @property
    def is_empty(self) -> bool:
        return not any(
            [
                self.current_task,
                self.confirmed_decisions,
                self.current_focus,
                self.open_questions,
                self.next_likely_action,
                self.reference_bindings,
            ]
        )

    def render(self) -> str:
        """Render the snapshot as a structured system message text."""
        parts: list[str] = []

        if self.current_task:
            parts.append(f"Current task: {self.current_task}")

        if self.confirmed_decisions:
            items = "\n- ".join(self.confirmed_decisions)
            parts.append(f"Confirmed decisions:\n- {items}")

        if self.current_focus:
            parts.append(f"Current focus: {self.current_focus}")

        if self.open_questions:
            items = "\n- ".join(self.open_questions)
            parts.append(f"Open questions:\n- {items}")

        if self.next_likely_action:
            parts.append(f"Next likely action: {self.next_likely_action}")

        if self.reference_bindings:
            bindings = "\n- ".join(
                f'"{k}" → {v}' for k, v in self.reference_bindings.items()
            )
            parts.append(f"Reference bindings:\n- {bindings}")

        return "[Conversation continuity]\n" + "\n".join(parts)

    def to_message(self) -> Message:
        msg = Message(role="system", content=self.render())
        from mindbot.utils import estimate_tokens

        msg.token_count = estimate_tokens(msg.text)
        return msg


_SNAPSHOT_PROMPT = """You maintain a structured conversation continuity snapshot.
Update it with the latest turn below.

Rules:
- Update incrementally: preserve existing info unless the new turn changes it.
- Only include decisions that were explicitly confirmed (not tentative).
- Reference bindings capture deictic references ("this", "that", "next step",
  "the previous", etc.) from the most recent turns.
- Be concise: one sentence per item.
- If the user shifts to a completely new task, replace Current task + focus.

{prev_section}
Latest turn:
User: {user}
Assistant: {assistant}

Output ONLY the updated snapshot in this format (no preamble or commentary):

Current task: <one line>
Confirmed decisions:
- <decision>
Current focus: <one line>
Open questions:
- <question>
Next likely action: <one line>
Reference bindings:
- "phrase" → referent
"""


def _format_previous(snapshot: ConversationContinuitySnapshot) -> str:
    if snapshot.is_empty:
        return ""
    return f"Previous snapshot:\n{snapshot.render()}\n"


def _parse_snapshot(text: str) -> ConversationContinuitySnapshot:
    snapshot = ConversationContinuitySnapshot(updated_at=time.time())

    def _section(name: str) -> str:
        # Match "Name:" or "Name:\n- item" sections
        pattern = rf"^{re.escape(name)}:\s*(.*?)(?=^(?:Current task|Confirmed decisions|Current focus|Open questions|Next likely action|Reference bindings):|\Z)"
        m = re.search(pattern, text, re.MULTILINE | re.DOTALL)
        if not m:
            return ""
        return m.group(1).strip()

    def _list_items(raw: str) -> list[str]:
        if not raw:
            return []
        items: list[str] = []
        for line in raw.split("\n"):
            stripped = line.strip()
            if stripped.startswith("- "):
                items.append(stripped[2:].strip())
            elif stripped:
                items.append(stripped)
        return [i for i in items if i]

    def _dict_items(raw: str) -> dict[str, str]:
        if not raw:
            return {}
        result: dict[str, str] = {}
        for line in raw.split("\n"):
            stripped = line.strip()
            if stripped.startswith("- "):
                stripped = stripped[2:]
            m = re.match(r'"([^"]+)"\s*→\s*(.*)', stripped)
            if m:
                result[m.group(1)] = m.group(2).strip()
            elif "→" in stripped:
                parts = stripped.split("→", 1)
                key = parts[0].strip().strip('"')
                val = parts[1].strip()
                if key:
                    result[key] = val
        return result

    snapshot.current_task = _section("Current task")
    snapshot.confirmed_decisions = _list_items(_section("Confirmed decisions"))
    snapshot.current_focus = _section("Current focus")
    snapshot.open_questions = _list_items(_section("Open questions"))
    snapshot.next_likely_action = _section("Next likely action")
    snapshot.reference_bindings = _dict_items(_section("Reference bindings"))

    return snapshot


_SNAPSHOT_PROMPT_FROM_TURNS = """You maintain a structured conversation continuity snapshot.
Update it with the recent conversation turns below.

Rules:
- Extract the current task, confirmed decisions, focus, open questions,
  likely next action, and deictic reference bindings from the turns.
- Only include decisions that were explicitly confirmed (not tentative).
- Reference bindings capture deictic references ("this", "that", "next step",
  "the previous", etc.) — map each phrase to what it points to.
- Be concise: one sentence per item.
- If no clear information for a section, leave it blank.

{prev_section}
Recent conversation:
{recent_turns}

Output ONLY the updated snapshot in this format (no preamble or commentary):

Current task: <one line>
Confirmed decisions:
- <decision>
Current focus: <one line>
Open questions:
- <question>
Next likely action: <one line>
Reference bindings:
- "phrase" → referent
"""


def _format_turns(messages: list[Message], limit: int = 8) -> str:
    """Format non-system messages into a text block for the snapshot prompt."""
    non_system = [m for m in messages if m.role != "system"][-limit:]
    return "\n".join(f"[{m.role}]: {m.text}" for m in non_system)


async def update_snapshot(
    llm: ProviderAdapter,
    prev: ConversationContinuitySnapshot | None,
    user_message: str,
    assistant_message: str,
) -> ConversationContinuitySnapshot:
    """Ask the LLM to produce an updated snapshot from *prev* + new turn.

    Returns a fresh :class:`ConversationContinuitySnapshot`.  If the LLM
    call fails the previous snapshot is returned unchanged.
    """
    prev_section = _format_previous(prev) if prev else ""
    prompt = _SNAPSHOT_PROMPT.format(
        prev_section=prev_section,
        user=user_message,
        assistant=assistant_message,
    )
    try:
        response = await llm.chat([Message(role="user", content=prompt)])
        return _parse_snapshot(response.content)
    except Exception:
        logger.warning(
            "Failed to update conversation continuity snapshot; keeping previous"
        )
        return prev or ConversationContinuitySnapshot(updated_at=time.time())


async def update_snapshot_from_messages(
    llm: ProviderAdapter,
    prev: ConversationContinuitySnapshot | None,
    messages: list[Message],
    *,
    recent_n: int = 8,
) -> ConversationContinuitySnapshot:
    """Build a snapshot from the conversation block's recent messages.

    Called by :class:`~mindbot.context.manager.ContextManager` after
    compaction or when a soft trigger fires.  Uses the most recent
    *recent_n* non-system messages as input.
    """
    prev_section = _format_previous(prev) if prev else ""
    turns_text = _format_turns(messages, limit=recent_n)
    if not turns_text:
        return prev or ConversationContinuitySnapshot(updated_at=time.time())

    prompt = _SNAPSHOT_PROMPT_FROM_TURNS.format(
        prev_section=prev_section,
        recent_turns=turns_text,
    )
    try:
        response = await llm.chat([Message(role="user", content=prompt)])
        return _parse_snapshot(response.content)
    except Exception:
        logger.warning(
            "Failed to update conversation continuity snapshot; keeping previous"
        )
        return prev or ConversationContinuitySnapshot(updated_at=time.time())
