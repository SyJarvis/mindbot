"""模型路由器 - 为每个请求选择最合适的 (实例, 端点, 模型)。

选择优先级（从高到低）：
1. 媒体规则：对话包含图片时，优先选择支持视觉的模型
2. 关键词规则：按优先级降序匹配，首个匹配关键词的规则生效
3. 复杂度：根据文本特征自动估算复杂度等级
4. 默认：使用 ``config.agent.model`` 配置的模型
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mindbot.config.schema import Config
    from mindbot.context.models import Message

from mindbot.routing.models import ModelCandidate, RoutingDecision


class ComplexityScorer:
    """复杂度评分器 - 根据文本特征估算任务复杂度。

    考虑的特征：
    - 文本长度
    - 代码块
    - 数字/数学表达式
    - 技术术语
    """

    _WORD_RE = re.compile(r"\S+")
    _CODE_RE = re.compile(r"```|`[^`]+`")
    _MATH_RE = re.compile(r"\d+\s*[\+\-\*\/]\s*\d+|[a-z]\s*=\s*\d+")

    def score(self, text: str) -> tuple[float, str, list[str]]:
        """返回 (分数, 等级, 原因列表)。

        分数范围 0-1，等级为 "low"/"medium"/"high"。
        """
        words = self._WORD_RE.findall(text)
        word_count = len(words)

        reasons = []
        score = 0.0

        # 长度评分（约 300 词为"中等"基准）
        length_score = min(word_count / 300, 1.0)
        score += length_score * 0.3
        if word_count > 200:
            reasons.append("long_text")

        # 代码检测
        if self._CODE_RE.search(text):
            score += 0.4
            reasons.append("code")

        # 数学表达式检测
        if self._MATH_RE.search(text):
            score += 0.2
            reasons.append("math")

        # 技术关键词检测
        tech_keywords = [
            "algorithm", "function", "class", "method", "variable",
            "数据结构", "算法", "函数", "类", "变量",
        ]
        lower_text = text.lower()
        if any(kw in lower_text for kw in tech_keywords):
            score += 0.1
            reasons.append("technical")

        # 确定等级
        if score < 0.3:
            level = "low"
        elif score < 0.6:
            level = "medium"
        else:
            level = "high"

        return min(score, 1.0), level, reasons


class ModelRouter:
    """无状态路由器：根据消息和配置返回路由决策。

    从 ``config.providers`` 读取所有声明的模型和端点，
    从 ``config.routing.rules`` 读取关键词规则。不发起网络请求。
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._scorer = ComplexityScorer()
        self._cached_candidates: list[ModelCandidate] | None = None

    def invalidate_cache(self) -> None:
        """清除缓存候选（配置重载后调用）。"""
        self._cached_candidates = None

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def select_model(self, messages: list[Message]) -> RoutingDecision:
        """根据消息返回路由决策。"""
        user_text = self._extract_user_text(messages)

        # 1. 媒体规则（视觉）
        if self._has_images(messages):
            return self._select_by_capability(
                "vision", user_text, rule_hit="media:image"
            )

        # 2. 关键词规则（按优先级降序）
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

        # 3. 复杂度评估
        score, level, reasons = self._scorer.score(user_text)
        return self._select_by_level(
            level,
            rule_hit=f"complexity:{reasons[:2]}",
            score=score,
        )

    def get_model_list(self) -> list[str]:
        """返回所有可用模型，格式为 "instance/model"。"""
        return [f"{c.instance}/{c.model_id}" for c in self._collect_all_candidates()]

    # ------------------------------------------------------------------
    # 选择辅助方法
    # ------------------------------------------------------------------

    def _select_by_level(
        self, level: str, *, rule_hit: str, score: float
    ) -> RoutingDecision:
        """查找匹配指定等级的候选；失败时降级到相邻等级。"""
        candidates = self._collect_candidates_by_level(level)
        # 添加跨等级降级候选（high → medium → low）
        fallback_levels = self._get_fallback_levels(level)
        for fb_level in fallback_levels:
            candidates.extend(self._collect_candidates_by_level(fb_level))
        if not candidates:
            candidates = self._collect_all_candidates()
        if not candidates:
            return self._default_decision(rule_hit=rule_hit, score=score)

        primary = candidates[0]
        fallbacks = [(c.instance, c.endpoint_index, c.model_id) for c in candidates[1:]]
        return RoutingDecision(
            instance=primary.instance,
            provider_type=primary.provider_type,
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
        """选择支持指定能力的模型（如 'vision'）。"""
        if capability == "vision":
            candidates = [c for c in self._collect_all_candidates() if c.vision]
        else:
            candidates = self._collect_all_candidates()

        if not candidates:
            score, level, _ = self._scorer.score(text)
            return self._select_by_level(
                level,
                rule_hit=rule_hit + "(fallback:no_vision_model)",
                score=score,
            )

        primary = candidates[0]
        fallbacks = [(c.instance, c.endpoint_index, c.model_id) for c in candidates[1:]]
        return RoutingDecision(
            instance=primary.instance,
            provider_type=primary.provider_type,
            endpoint_index=primary.endpoint_index,
            model_id=primary.model_id,
            level=primary.level,
            rule_hit=rule_hit,
            score=0.0,
            fallbacks=fallbacks,
        )

    def _default_decision(self, *, rule_hit: str, score: float) -> RoutingDecision:
        """配置中未找到模型时的默认决策。"""
        instance, model_id = self._parse_model_ref(self._config.agent.model)
        provider_type = self._get_provider_type(instance)
        return RoutingDecision(
            instance=instance,
            provider_type=provider_type,
            endpoint_index="0",
            model_id=model_id,
            level="medium",
            rule_hit=rule_hit + "(fallback:default)",
            score=score,
            fallbacks=[],
        )

    # ------------------------------------------------------------------
    # 候选枚举
    # ------------------------------------------------------------------

    def _collect_all_candidates(self) -> list[ModelCandidate]:
        """返回所有 provider 实例和端点中声明的模型。"""
        if self._cached_candidates is not None:
            return self._cached_candidates

        candidates: list[ModelCandidate] = []
        for instance_name, provider_cfg in self._config.providers.items():
            for endpoint_idx, model_id, model_config in provider_cfg.get_all_models():
                if isinstance(model_config, str):
                    continue

                if hasattr(model_config, "enabled") and not model_config.enabled:
                    continue

                candidates.append(
                    ModelCandidate(
                        instance=instance_name,
                        provider_type=provider_cfg.type,
                        endpoint_index=endpoint_idx,
                        model_id=model_config.id,
                        level=getattr(model_config, "level", "medium"),
                        vision=getattr(model_config, "vision", False),
                        model_config=model_config,
                    )
                )

        # 按等级排序（high → medium → low）作为 fallback 顺序
        level_order = {"high": 0, "medium": 1, "low": 2}
        candidates.sort(key=lambda c: level_order.get(c.level, 99))

        self._cached_candidates = candidates
        return candidates

    def _collect_candidates_by_level(self, level: str) -> list[ModelCandidate]:
        """返回精确匹配指定等级的候选。"""
        return [c for c in self._collect_all_candidates() if c.level == level]

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _get_fallback_levels(level: str) -> list[str]:
        """返回降级等级列表（high → medium → low）。"""
        level_chain = ["high", "medium", "low"]
        if level not in level_chain:
            return []
        idx = level_chain.index(level)
        return level_chain[idx + 1:]

    def _get_provider_type(self, instance: str) -> str:
        """查询 provider 实例的后端驱动类型。"""
        cfg = self._config.providers.get(instance)
        return cfg.type if cfg else "openai"

    # ------------------------------------------------------------------
    # 规则匹配
    # ------------------------------------------------------------------

    @staticmethod
    def _matches_keyword_rule(text: str, rule: Any) -> bool:
        """判断文本是否匹配关键词规则。"""
        lower = text.lower()

        if rule.min_length is not None and len(text) < rule.min_length:
            return False
        if rule.max_length is not None and len(text) > rule.max_length:
            return False

        if rule.keywords:
            return any(kw.lower() in lower for kw in rule.keywords)

        return True

    @staticmethod
    def _extract_user_text(messages: list[Message]) -> str:
        """从消息中提取用户文本。"""
        text_parts = []
        for msg in messages:
            if msg.role in ("user", "system"):
                if isinstance(msg.content, str):
                    text_parts.append(msg.content)
                elif isinstance(msg.content, list):
                    for part in msg.content:
                        if hasattr(part, "text"):
                            text_parts.append(part.text)
                        elif isinstance(part, str):
                            text_parts.append(part)
        return " ".join(text_parts)

    @staticmethod
    def _has_images(messages: list[Message]) -> bool:
        """判断消息中是否包含图片。"""
        for msg in messages:
            if isinstance(msg.content, list):
                for part in msg.content:
                    if hasattr(part, "type") and part.type == "image":
                        return True
                    if hasattr(part, "image"):
                        return True
        return False

    @staticmethod
    def _parse_model_ref(model_ref: str) -> tuple[str, str]:
        """解析 'instance/model' 为 (实例名, 模型名)。"""
        if "/" in model_ref:
            parts = model_ref.split("/")
            if len(parts) >= 2:
                return parts[0], parts[-1]
        return "unknown", model_ref
