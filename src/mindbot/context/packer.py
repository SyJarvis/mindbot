"""Cognitive workspace packer.

The packer turns a list of :class:`ContextItem` candidates into the
final ``list[Message]`` that will be sent to the LLM for one turn.

Algorithm (deterministic, single pass)::

    1. Sort items by (priority desc, salience desc).
    2. Phase A – required items are guaranteed to enter; if their full
       cost already exceeds the budget, each one is compressed (using
       its ``compress`` callback) towards the largest share it could
       still reasonably claim.
    3. Phase B – optional items try, in order, to claim the remaining
       budget.  Each item gets either:
        * its full form, if it fits;
        * a compressed form, if it has a ``compress`` callback and the
          compressed version fits;
        * dropped, otherwise.
    4. Final messages are emitted in the canonical *source* order so
       the LLM sees a consistent layout regardless of pack order.

The packer never mutates input items.  It produces a
:class:`ContextPackResult` describing every decision made, which is
useful for logging and tests.
"""

from __future__ import annotations

from dataclasses import dataclass

from mindbot.context.items import ContextItem, ContextPackResult, ItemSource, PackedItem
from mindbot.context.models import Message
from mindbot.utils import estimate_tokens


# Canonical send order.  Items are emitted in this order regardless of
# pack order so the LLM sees: identity → environment → procedural
# memory → episodic memory → conversation → goal hint → user input.
_CANONICAL_ORDER: dict[ItemSource, int] = {
    "system": 0,
    "env": 1,
    "skill_overview": 2,
    "skill_detail": 3,
    "memory": 4,
    "conversation": 5,
    "intent": 6,
    "user": 7,
}


@dataclass
class PackerConfig:
    """Tunables for :class:`ContextPacker`."""

    # Minimum tokens reserved for the LLM response.  Subtracted from
    # ``total_budget`` before any item competes for space.
    response_reserve: int = 1024

    # Floor for a compressed item.  An item compressed to fewer tokens
    # than this is treated as dropped (signal too noisy to include).
    min_item_tokens: int = 16


class ContextPacker:
    """Assemble per-turn LLM input from a pool of :class:`ContextItem`."""

    def __init__(self, config: PackerConfig | None = None) -> None:
        self._config = config or PackerConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def pack(
        self,
        items: list[ContextItem],
        *,
        total_budget: int,
        response_reserve: int | None = None,
    ) -> ContextPackResult:
        """Pack *items* into a working-memory snapshot.

        Args:
            items: Candidate items collected by the input builder.  May
                contain empty items; they are silently filtered.
            total_budget: Total token budget for the prompt (typically
                ``ContextConfig.max_tokens``).
            response_reserve: Optional override for response reserve.

        Returns:
            A :class:`ContextPackResult` with the final ``messages``
            list and per-item decisions.
        """
        reserve = (
            response_reserve if response_reserve is not None else self._config.response_reserve
        )
        budget = max(0, total_budget - reserve)

        non_empty = [it for it in items if not it.is_empty]

        # Phase A: required items.
        required = [it for it in non_empty if it.required]
        optional = [it for it in non_empty if not it.required]

        decisions: list[PackedItem] = []
        used = 0

        for item in self._sort_for_pack(required):
            packed, cost = self._place_required(item, remaining=budget - used)
            decisions.append(packed)
            used += cost

        # Phase B: optional items compete for the leftover budget.
        for item in self._sort_for_pack(optional):
            remaining = budget - used
            if remaining <= 0:
                decisions.append(
                    PackedItem.dropped_from(item, reason="no budget left")
                )
                continue

            packed, cost = self._place_optional(item, remaining=remaining)
            decisions.append(packed)
            used += cost

        # Emit messages in canonical source order.
        kept = sorted(
            (d for d in decisions if not d.dropped),
            key=lambda d: (_CANONICAL_ORDER.get(d.source, 99), -d.priority),
        )
        messages: list[Message] = []
        for d in kept:
            messages.extend(d.messages)

        return ContextPackResult(
            messages=messages,
            token_count=used,
            budget=budget,
            items=decisions,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _sort_for_pack(items: list[ContextItem]) -> list[ContextItem]:
        return sorted(items, key=lambda it: (-it.priority, -it.salience, it.name))

    def _place_required(
        self, item: ContextItem, *, remaining: int
    ) -> tuple[PackedItem, int]:
        """Required items always end up in the result.

        If the item already fits, keep it verbatim.  Otherwise try the
        compression callback against the remaining budget.  As a last
        resort, character-truncate the first message so the workspace
        is not corrupted by a single oversized item.
        """
        if item.token_count <= remaining:
            return PackedItem.kept(item, compressed=False, reason="fits"), item.token_count

        if item.compress is not None and remaining > 0:
            target = max(self._config.min_item_tokens, remaining)
            compressed = item.compress(target)
            cost = _sum_tokens(compressed)
            if cost <= remaining and cost > 0:
                return (
                    PackedItem(
                        name=item.name,
                        source=item.source,
                        messages=list(compressed),
                        token_count=cost,
                        salience=item.salience,
                        priority=item.priority,
                        required=True,
                        compressed=True,
                        dropped=False,
                        reason=f"compressed to fit ({cost}/{remaining})",
                    ),
                    cost,
                )

        # Last-resort character truncation on the first message.
        truncated_msgs, cost = _truncate_messages(item.messages, max(remaining, 0))
        return (
            PackedItem(
                name=item.name,
                source=item.source,
                messages=truncated_msgs,
                token_count=cost,
                salience=item.salience,
                priority=item.priority,
                required=True,
                compressed=True,
                dropped=False,
                reason=f"hard-truncated ({cost}/{remaining})",
            ),
            cost,
        )

    def _place_optional(
        self, item: ContextItem, *, remaining: int
    ) -> tuple[PackedItem, int]:
        if item.token_count <= remaining:
            return PackedItem.kept(item, compressed=False, reason="fits"), item.token_count

        if item.compress is not None:
            target = max(self._config.min_item_tokens, remaining)
            compressed = item.compress(target)
            cost = _sum_tokens(compressed)
            if 0 < cost <= remaining:
                return (
                    PackedItem(
                        name=item.name,
                        source=item.source,
                        messages=list(compressed),
                        token_count=cost,
                        salience=item.salience,
                        priority=item.priority,
                        required=False,
                        compressed=True,
                        dropped=False,
                        reason=f"compressed to fit ({cost}/{remaining})",
                    ),
                    cost,
                )

        return (
            PackedItem.dropped_from(
                item,
                reason=f"too large ({item.token_count} > {remaining})",
            ),
            0,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sum_tokens(messages: list[Message]) -> int:
    total = 0
    for m in messages:
        if m.token_count <= 0:
            m.token_count = estimate_tokens(m.text)
        total += m.token_count
    return total


def _truncate_messages(
    messages: list[Message], budget: int
) -> tuple[list[Message], int]:
    """Character-truncate the first message until it fits.

    Used only as a last-resort safety net for required items that have
    no compression strategy and exceed the available budget.  Later
    messages are dropped.
    """
    if budget <= 0 or not messages:
        return [], 0

    first = messages[0]
    text = first.text if isinstance(first.content, str) else ""
    if not text:
        return [], 0

    cost = estimate_tokens(text)
    while text and cost > budget:
        cut = max(1, len(text) // 8)
        text = text[: max(0, len(text) - cut)]
        cost = estimate_tokens(text) if text else 0

    if not text:
        return [], 0

    truncated = Message(role=first.role, content=text)
    truncated.tool_calls = first.tool_calls
    truncated.reasoning_content = first.reasoning_content
    truncated.tool_call_id = first.tool_call_id
    truncated.token_count = estimate_tokens(text)
    return [truncated], truncated.token_count
