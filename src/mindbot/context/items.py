"""Cognitive workspace candidate items.

A :class:`ContextItem` represents a single candidate piece of information
that *may* enter the working-memory snapshot for one turn.  Items are
collected by :class:`~mindbot.agent.input_builder.InputBuilder` from
multiple sources (system prompt, skills, memory, conversation, intent,
user input) and handed to :class:`~mindbot.context.packer.ContextPacker`,
which decides what to keep based on attention scores and the current
token budget.

Design notes
------------
- ``messages`` are the *full* messages an item carries.  They are kept
  separate from token math so the packer can choose to keep all, some,
  or a compressed version of them.
- ``token_count`` is the cost of the *full* item.  ``compress`` produces
  a shorter version when the packer cannot afford the full cost.
- ``salience`` is a normalized [0, 1] attention score; ``priority`` is
  a coarse tier used as a tie-breaker (higher = entered earlier).
- ``required=True`` items always enter the workspace; the packer will
  shrink other items first.  If they still do not fit, the packer falls
  back to compressing the required item itself.
- ``cache_scope`` is metadata describing how stable an item is across
  turns.  It's surfaced for future cache-boundary work but does not yet
  drive packer decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

from mindbot.context.models import Message
from mindbot.utils import estimate_tokens


ItemSource = Literal[
    "system",
    "env",
    "skill_overview",
    "skill_detail",
    "memory",
    "conversation",
    "intent",
    "user",
]

CacheScope = Literal["global", "session", "turn"]


@dataclass
class ContextItem:
    """A single candidate piece of context for one turn."""

    name: str
    source: ItemSource
    messages: list[Message]
    token_count: int = 0
    salience: float = 0.5
    priority: int = 0
    required: bool = False
    cache_scope: CacheScope = "turn"
    compress: Callable[[int], list[Message]] | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.token_count <= 0 and self.messages:
            self.token_count = sum(
                _ensure_token_count(m) for m in self.messages
            )

    @property
    def is_empty(self) -> bool:
        return not self.messages or self.token_count <= 0


def _ensure_token_count(msg: Message) -> int:
    if msg.token_count > 0:
        return msg.token_count
    msg.token_count = estimate_tokens(msg.text)
    return msg.token_count


@dataclass
class PackedItem:
    """Result of packing a single item: kept messages + actual cost."""

    name: str
    source: ItemSource
    messages: list[Message]
    token_count: int
    salience: float
    priority: int
    required: bool
    compressed: bool = False
    dropped: bool = False
    reason: str = ""

    @classmethod
    def kept(cls, item: ContextItem, *, compressed: bool, reason: str) -> "PackedItem":
        return cls(
            name=item.name,
            source=item.source,
            messages=list(item.messages),
            token_count=item.token_count,
            salience=item.salience,
            priority=item.priority,
            required=item.required,
            compressed=compressed,
            dropped=False,
            reason=reason,
        )

    @classmethod
    def dropped_from(cls, item: ContextItem, *, reason: str) -> "PackedItem":
        return cls(
            name=item.name,
            source=item.source,
            messages=[],
            token_count=0,
            salience=item.salience,
            priority=item.priority,
            required=item.required,
            compressed=False,
            dropped=True,
            reason=reason,
        )


@dataclass
class ContextPackResult:
    """Outcome of one packing pass.

    The packed messages are produced in canonical send order so the
    caller can hand ``messages`` directly to a provider adapter.
    """

    messages: list[Message]
    token_count: int
    budget: int
    items: list[PackedItem]

    @property
    def kept_items(self) -> list[PackedItem]:
        return [it for it in self.items if not it.dropped]

    @property
    def dropped_items(self) -> list[PackedItem]:
        return [it for it in self.items if it.dropped]

    def summary(self) -> str:
        parts: list[str] = []
        for it in self.items:
            tag = "drop" if it.dropped else ("compress" if it.compressed else "keep")
            parts.append(
                f"{it.name}({it.source})[{tag} sal={it.salience:.2f} "
                f"pri={it.priority} tok={it.token_count}]"
            )
        return " ".join(parts)
