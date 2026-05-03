"""端点管理器 - 管理多个端点的负载均衡和故障转移。

EndpointManager 负责：
- 轮询、随机、优先级策略的端点选择
- 端点健康状态追踪（失败计数）
- 自动回退到健康端点
"""

from __future__ import annotations

import random
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mindbot.config.schema import Config, EndpointConfig

from mindbot.routing.models import EndpointCandidate
from mindbot.logging import logger



@dataclass
class EndpointHealth:
    """端点健康状态追踪。"""

    failures: int = 0
    last_failure_time: float = 0.0
    last_success_time: float = 0.0
    is_healthy: bool = True
    # 增强字段：主动健康监控
    provider_type: str = "unknown"
    status: str = "active"  # active, inactive, probing
    last_probe_time: float = 0.0
    last_probe_success: bool | None = None
    last_probe_latency_ms: float = 0.0
    latency_history: list[float] = field(default_factory=list)

    def record_success(self) -> None:
        """记录成功请求。"""
        self.failures = 0
        self.last_success_time = time.time()
        self.is_healthy = True
        self.status = "active"

    def record_failure(self) -> None:
        """记录失败请求。"""
        self.failures += 1
        self.last_failure_time = time.time()
        if self.failures >= 1:
            self.is_healthy = False
            self.status = "inactive"

    def should_try(self) -> bool:
        """检查端点是否应该被尝试。"""
        if self.is_healthy:
            return True
        # 失败后等待 5 分钟 cooldown 才重新尝试
        return time.time() - self.last_failure_time > 300

    def record_probe_success(self, latency_ms: float) -> None:
        """记录成功的健康探测。"""
        self.last_probe_time = time.time()
        self.last_probe_success = True
        self.last_probe_latency_ms = latency_ms
        self.latency_history.append(latency_ms)
        if len(self.latency_history) > 10:
            self.latency_history.pop(0)

    def record_probe_failure(self) -> None:
        """记录失败的健康探测。"""
        self.last_probe_time = time.time()
        self.last_probe_success = False
        self.last_probe_latency_ms = 0.0

    def mark_healthy_from_probe(self) -> None:
        """探测恢复成功后标记端点为健康。"""
        self.is_healthy = True
        self.failures = 0
        self.status = "active"
        self.last_success_time = time.time()

    def mark_probing(self) -> None:
        """标记端点正在探测中。"""
        self.status = "probing"

    def get_avg_latency(self) -> float | None:
        """获取最近历史记录的平均延迟。"""
        if not self.latency_history:
            return None
        return sum(self.latency_history) / len(self.latency_history)


class EndpointManager:
    """端点选择和健康状态管理器。

    支持三种策略：
    - round-robin: 按顺序轮询端点
    - random: 随机选择端点（按权重加权）
    - priority: 总是尝试第一个端点，失败后回退到其他端点
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._health: dict[str, EndpointHealth] = defaultdict(EndpointHealth)
        self._round_robin_indices: dict[str, int] = defaultdict(int)

    def get_endpoint(
        self,
        instance: str,
        endpoint_index: str | None = None,
        strategy: str | None = None,
    ) -> EndpointCandidate:
        """获取指定 provider 实例的端点。

        Args:
            instance: Provider 实例名（config.providers 中的用户定义键）
            endpoint_index: 指定端点索引（为 None 时使用策略选择）
            strategy: 选择策略（为 None 时使用 provider 配置）

        Returns:
            选中的端点候选
        """
        provider_cfg = self._config.providers.get(instance)
        if not provider_cfg:
            raise ValueError(f"Provider instance not found: {instance}")

        endpoints = provider_cfg.get_effective_endpoints()
        if not endpoints:
            raise ValueError(f"No endpoints configured for provider instance: {instance}")

        # 指定端点索引时直接返回
        if endpoint_index is not None:
            idx = int(endpoint_index)
            if 0 <= idx < len(endpoints):
                return EndpointCandidate(
                    instance=instance,
                    endpoint_index=endpoint_index,
                    weight=endpoints[idx].weight,
                )

        # 使用策略选择端点
        strategy = strategy or provider_cfg.strategy
        idx = self._select_endpoint_index(instance, endpoints, strategy)
        return EndpointCandidate(
            instance=instance,
            endpoint_index=str(idx),
            weight=endpoints[idx].weight,
        )

    def get_all_healthy_endpoints(
        self,
        instance: str,
        include_unhealthy: bool = False,
    ) -> list[EndpointCandidate]:
        """获取指定 provider 实例的所有健康端点。

        Args:
            instance: Provider 实例名
            include_unhealthy: 为 True 时，不健康端点排在末尾

        Returns:
            端点候选列表，按健康状态排序
        """
        provider_cfg = self._config.providers.get(instance)
        if not provider_cfg:
            return []

        endpoints = provider_cfg.get_effective_endpoints()
        healthy = []
        unhealthy = []

        for idx, endpoint in enumerate(endpoints):
            key = f"{instance}:{idx}"
            health = self._health[key]

            candidate = EndpointCandidate(
                instance=instance,
                endpoint_index=str(idx),
                weight=endpoint.weight,
            )

            if health.should_try():
                healthy.append(candidate)
            else:
                unhealthy.append(candidate)

        result = healthy
        if include_unhealthy:
            result.extend(unhealthy)
        return result

    def record_success(self, instance: str, endpoint_index: str) -> None:
        """记录成功请求。"""
        key = f"{instance}:{endpoint_index}"
        self._health[key].record_success()

    def record_failure(self, instance: str, endpoint_index: str) -> None:
        """记录失败请求。"""
        key = f"{instance}:{endpoint_index}"
        self._health[key].record_failure()

    def should_try(self, instance: str, endpoint_index: str) -> bool:
        """检查端点是否应该被尝试。"""
        key = f"{instance}:{endpoint_index}"
        return self._health[key].should_try()

    def get_health_status(self) -> dict[str, dict[str, Any]]:
        """获取所有端点的健康状态。"""
        result = {}
        for key, health in self._health.items():
            instance, endpoint_idx = key.split(":")
            result[key] = {
                "instance": instance,
                "endpoint_index": endpoint_idx,
                "is_healthy": health.is_healthy,
                "failures": health.failures,
                "last_success_time": health.last_success_time,
                "last_failure_time": health.last_failure_time,
                "status": health.status,
                "provider_type": health.provider_type,
                "last_probe_time": health.last_probe_time,
                "last_probe_success": health.last_probe_success,
                "last_probe_latency_ms": health.last_probe_latency_ms,
                "avg_latency_ms": health.get_avg_latency(),
            }
        return result

    def get_all_inactive_endpoints(self) -> list[dict[str, Any]]:
        """获取所有不健康/inactive 端点用于主动探测。

        返回包含 instance、endpoint_index、provider_type 等信息的字典列表。
        """
        result = []
        for instance_name, provider_cfg in self._config.providers.items():
            endpoints = provider_cfg.get_effective_endpoints()
            for idx, endpoint in enumerate(endpoints):
                key = f"{instance_name}:{idx}"
                health = self._health[key]

                if not health.is_healthy:
                    result.append({
                        "instance": instance_name,
                        "endpoint_index": str(idx),
                        "provider_type": provider_cfg.type,
                        "base_url": endpoint.base_url,
                        "api_key": endpoint.api_key,
                        "key": key,
                    })
        return result

    def get_endpoint_info(
        self, instance: str, endpoint_index: str
    ) -> dict[str, Any]:
        """获取端点详细信息用于探测。"""
        provider_cfg = self._config.providers.get(instance)
        if not provider_cfg:
            raise ValueError(f"Provider instance not found: {instance}")

        endpoints = provider_cfg.get_effective_endpoints()
        idx = int(endpoint_index)
        if idx >= len(endpoints):
            raise ValueError(f"Invalid endpoint index: {endpoint_index}")

        endpoint = endpoints[idx]
        return {
            "instance": instance,
            "endpoint_index": endpoint_index,
            "provider_type": provider_cfg.type,
            "base_url": endpoint.base_url,
            "api_key": endpoint.api_key,
            "key": f"{instance}:{endpoint_index}",
        }

    def mark_healthy(self, instance: str, endpoint_index: str) -> None:
        """标记端点为健康状态（探测恢复成功后）。"""
        key = f"{instance}:{endpoint_index}"
        health = self._health[key]
        health.mark_healthy_from_probe()
        logger.info("Endpoint {} recovered to healthy state", key)

    def mark_probing(self, instance: str, endpoint_index: str) -> None:
        """标记端点正在探测中。"""
        key = f"{instance}:{endpoint_index}"
        self._health[key].mark_probing()

    def set_provider_type(
        self, instance: str, endpoint_index: str, provider_type: str
    ) -> None:
        """存储 provider 类型用于健康检查路由。"""
        key = f"{instance}:{endpoint_index}"
        self._health[key].provider_type = provider_type

    def record_probe_result(
        self,
        instance: str,
        endpoint_index: str,
        success: bool,
        latency_ms: float,
    ) -> None:
        """记录健康探测结果。"""
        key = f"{instance}:{endpoint_index}"
        health = self._health[key]
        if success:
            health.record_probe_success(latency_ms)
        else:
            health.record_probe_failure()

    def reset_health(self) -> None:
        """重置所有健康状态追踪（配置重载后使用）。"""
        self._health.clear()
        self._round_robin_indices.clear()

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    def _select_endpoint_index(
        self,
        instance: str,
        endpoints: list[EndpointConfig],
        strategy: str,
    ) -> int:
        """根据策略选择端点索引。"""
        if strategy == "round-robin":
            return self._select_round_robin(instance, len(endpoints))
        elif strategy == "random":
            return self._select_weighted_random(endpoints)
        elif strategy == "priority":
            return self._select_priority(endpoints)
        else:
            return self._select_round_robin(instance, len(endpoints))

    def _select_round_robin(self, instance: str, count: int) -> int:
        """轮询方式选择下一个端点。"""
        idx = self._round_robin_indices[instance]
        self._round_robin_indices[instance] = (idx + 1) % count
        return idx

    @staticmethod
    def _select_weighted_random(endpoints: list[EndpointConfig]) -> int:
        """按权重随机选择端点。"""
        weights = [e.weight for e in endpoints]
        total_weight = sum(weights)
        if total_weight == 0:
            return random.randint(0, len(endpoints) - 1)

        r = random.uniform(0, total_weight)
        cumulative = 0
        for idx, weight in enumerate(weights):
            cumulative += weight
            if r <= cumulative:
                return idx
        return len(endpoints) - 1

    @staticmethod
    def _select_priority(endpoints: list[EndpointConfig]) -> int:
        """优先级模式：总是返回第一个端点。"""
        return 0
