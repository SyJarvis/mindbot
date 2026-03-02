"""ModelRouter – selects the most appropriate (provider, endpoint, model) for a request.

Selection priority (highest to lowest):
1. Media rule: if the conversation contains images, prefer a vision-capable model.
2. Keyword rules: first rule whose keywords match the user text wins (sorted by priority desc).
3. Complexity: automatic level estimation from text features.
4. Default: the model configured in ``config.agent.model``.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mindbot.config.schema import Config, ModelConfig
    from mindbot.context.models import Message

from mindbot.routing.models import ModelCandidate, RoutingDecision


class ComplexityScorer:
    """Estimate task complexity from text features.

    Features considered:
    - Text length
    - Code blocks
    - Numbers/math expressions
    - Technical terms
    """

    _WORD_RE = re.compile(r"\S+")
    _CODE_RE = re.compile(r"```|`[^`]+`")
    _MATH_RE = re.compile(r"\d+\s*[\+\-\*\/]\s*\d+|[a-z]\s*=\s*\d+")

    def score(self, text: str) -> tuple[float, str, list[str]]:
        """Return (score, level, reasons).

        Score is 0-1, level is "low"/"medium"/"high".
        """
        words = self._WORD_RE.findall(text)
        word_count = len(words)

        reasons = []
        score = 0.0

        # Length score (normalized to ~300 words as "medium")
        length_score = min(word_count / 300, 1.0)
        score += length_score * 0.3
        if word_count > 200:
            reasons.append("long_text")

        # Code detection
        if self._CODE_RE.search(text):
            score += 0.4
            reasons.append("code")

        # Math detection
        if self._MATH_RE.search(text):
            score += 0.2
            reasons.append("math")

        # Technical keywords
        tech_keywords = [
            "algorithm", "function", "class", "method", "variable",
            "数据结构", "算法", "函数", "类", "变量",
        ]
        lower_text = text.lower()
        if any(kw in lower_text for kw in tech_keywords):
            score += 0.1
            reasons.append("technical")

        # Determine level
        if score < 0.3:
            level = "low"
        elif score < 0.6:
            level = "medium"
        else:
            level = "high"

        return min(score, 1.0), level, reasons


class ModelRouter:
    """Stateless router: given messages and config, returns a :class:`RoutingDecision`.

    The router reads ``config.providers`` to enumerate all declared models across
    all endpoints and ``config.routing.rules`` for keyword rules. It never makes network calls.
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._scorer = ComplexityScorer()
        self._cached_candidates: list[ModelCandidate] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def select_model(self, messages: list[Message]) -> RoutingDecision:
        """Return the routing decision for the given *messages*."""
        user_text = self._extract_user_text(messages)

        # 1. Media rule (vision)
        if self._has_images(messages):
            return self._select_by_capability(
                "vision", user_text, rule_hit="media:image"
            )

        # 2. Keyword rules (sorted by priority descending)
        for rule in sorted(
            self._config.routing.rules,
            key=lambda r: r.priority,
            reverse=True
        ):
            if self._matches_keyword_rule(user_text, rule):
                return self._select_by_level(
                    rule.level,
                    rule_hit=f"keyword:{rule.keywords[:2]}",
                    score=0.0,
                )

        # 3. Complexity evaluation
        score, level, reasons = self._scorer.score(user_text)
        return self._select_by_level(
            level,
            rule_hit=f"complexity:{reasons[:2]}",
            score=score,
        )

    def get_model_list(self) -> list[str]:
        """Return all available models as "provider/endpoint/model" strings."""
        return [c.key for c in self._collect_all_candidates()]

    # ------------------------------------------------------------------
    # Selection helpers
    # ------------------------------------------------------------------

    def _select_by_level(
        self, level: str, *, rule_hit: str, score: float
    ) -> RoutingDecision:
        """Find candidates matching *level*; fall back to adjacent levels."""
        candidates = self._collect_candidates_by_level(level)
        if not candidates:
            # Widen: try all candidates
            candidates = self._collect_all_candidates()
        if not candidates:
            # Last resort: use the default agent model
            return self._default_decision(rule_hit=rule_hit, score=score)

        primary = candidates[0]
        fallbacks = [(c.provider, c.endpoint_index, c.model_id) for c in candidates[1:]]
        return RoutingDecision(
            provider=primary.provider,
            endpoint_index=primary.endpoint_index,
            model_id=primary.model_id,
            level=primary.level,
            rule_hit=rule_hit,
            score=score,
            fallbacks=fallbacks,
        )

    def _select_by_capability(
        self, capability: str, text: str, *, rule_hit: str
    ) -> RoutingDecision:
        """Select a model that advertises *capability* (e.g. 'vision')."""
        if capability == "vision":
            candidates = [c for c in self._collect_all_candidates() if c.vision]
        else:
            candidates = self._collect_all_candidates()

        if not candidates:
            # Fall back to complexity-based selection
            score, level, _ = self._scorer.score(text)
            return self._select_by_level(
                level,
                rule_hit=rule_hit + "(fallback:no_vision_model)",
                score=score,
            )

        primary = candidates[0]
        fallbacks = [(c.provider, c.endpoint_index, c.model_id) for c in candidates[1:]]
        return RoutingDecision(
            provider=primary.provider,
            endpoint_index=primary.endpoint_index,
            model_id=primary.model_id,
            level=primary.level,
            rule_hit=rule_hit,
            score=0.0,
            fallbacks=fallbacks,
        )

    def _default_decision(self, *, rule_hit: str, score: float) -> RoutingDecision:
        """Fallback when no model is found in config."""
        provider, model_id = self._parse_model_ref(self._config.agent.model)
        return RoutingDecision(
            provider=provider,
            endpoint_index="0",  # Default to first endpoint
            model_id=model_id,
            level="medium",
            rule_hit=rule_hit + "(fallback:default)",
            score=score,
            fallbacks=[],
        )

    # ------------------------------------------------------------------
    # Candidate enumeration
    # ------------------------------------------------------------------

    def _collect_all_candidates(self) -> list[ModelCandidate]:
        """Return all models declared across all providers and endpoints."""
        if self._cached_candidates is not None:
            return self._cached_candidates

        candidates: list[ModelCandidate] = []
        for provider_name, provider_cfg in self._config.providers.items():
            for endpoint_idx, model_id, model_config in provider_cfg.get_all_models():
                if isinstance(model_config, str):
                    # This shouldn't happen with the new get_all_models implementation
                    continue

                # Check if model is enabled
                if hasattr(model_config, "enabled") and not model_config.enabled:
                    continue

                candidates.append(
                    ModelCandidate(
                        provider=provider_name,
                        endpoint_index=endpoint_idx,
                        model_id=model_config.id,
                        level=getattr(model_config, "level", "medium"),
                        vision=getattr(model_config, "vision", False),
                        model_config=model_config,
                    )
                )

        # Sort by level (high → medium → low) for fallback order
        level_order = {"high": 0, "medium": 1, "low": 2}
        candidates.sort(key=lambda c: level_order.get(c.level, 99))

        self._cached_candidates = candidates
        return candidates

    def _collect_candidates_by_level(self, level: str) -> list[ModelCandidate]:
        """Return candidates matching *level* exactly."""
        return [c for c in self._collect_all_candidates() if c.level == level]

    # ------------------------------------------------------------------
    # Rule matching
    # ------------------------------------------------------------------

    @staticmethod
    def _matches_keyword_rule(text: str, rule: Any) -> bool:
        """Return True if *text* matches the keyword rule."""
        lower = text.lower()

        # Length constraints
        if rule.min_length is not None and len(text) < rule.min_length:
            return False
        if rule.max_length is not None and len(text) > rule.max_length:
            return False

        # Keyword match (any keyword is sufficient)
        if rule.keywords:
            return any(kw.lower() in lower for kw in rule.keywords)

        # Pure length-based rule (no keywords specified)
        return True

    @staticmethod
    def _extract_user_text(messages: list[Message]) -> str:
        """Extract user text from messages."""
        text_parts = []
        for msg in messages:
            if msg.role in ("user", "system"):
                if isinstance(msg.content, str):
                    text_parts.append(msg.content)
                elif isinstance(msg.content, list):
                    # Extract text parts, skip images
                    for part in msg.content:
                        if hasattr(part, "text"):
                            text_parts.append(part.text)
                        elif isinstance(part, str):
                            text_parts.append(part)
        return " ".join(text_parts)

    @staticmethod
    def _has_images(messages: list[Message]) -> bool:
        """Return True if any message contains images."""
        for msg in messages:
            if isinstance(msg.content, list):
                for part in msg.content:
                    # Check if it's an image part
                    if hasattr(part, "type") and part.type == "image":
                        return True
                    if hasattr(part, "image"):
                        return True
        return False

    @staticmethod
    def _parse_model_ref(model_ref: str) -> tuple[str, str]:
        """Parse 'provider/model' or 'provider/endpoint/model' into (provider, model)."""
        parts = model_ref.split("/")
        if len(parts) >= 2:
            return parts[0], parts[-1]  # provider, model (ignore endpoint in ref)
        return "unknown", model_ref
