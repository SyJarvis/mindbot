"""HealthMonitor - proactive health probing for inactive providers."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mindbot.config.schema import Config
    from mindbot.routing.endpoint import EndpointManager

from mindbot.routing.health_check import HealthCheckRegistry
from mindbot.utils import get_logger

logger = get_logger("routing.health")


@dataclass
class HealthProbeConfig:
    """Configuration for health probing."""

    enabled: bool = True
    probe_interval_seconds: float = 30.0  # How often to probe inactive endpoints
    probe_timeout_seconds: float = 10.0  # Timeout for each probe attempt
    success_threshold: int = 1  # Number of successful probes to mark healthy


@dataclass
class ProbeResult:
    """Result of a health probe attempt."""

    endpoint_key: str
    instance: str
    endpoint_index: str
    provider_type: str
    success: bool
    latency_ms: float
    timestamp: float = field(default_factory=time.time)
    error_message: str | None = None


class HealthMonitor:
    """Proactive health monitoring for provider endpoints.

    Responsibilities:
    - Periodically probe inactive/unhealthy endpoints
    - Update EndpointManager health status on probe results
    - Provide health status for CLI/HTTP endpoints
    - Track probe history for diagnostics

    Lifecycle:
    - start(): Begin background probing task
    - stop(): Cancel background task
    """

    def __init__(
        self,
        config: "Config",
        endpoint_manager: "EndpointManager",
        probe_config: HealthProbeConfig | None = None,
    ) -> None:
        self._config = config
        self._endpoint_manager = endpoint_manager
        self._probe_config = probe_config or HealthProbeConfig()
        self._health_checker = HealthCheckRegistry(config)

        # Background task management
        self._probe_task: asyncio.Task | None = None
        self._running = False

        # Probe history (last N results per endpoint)
        self._probe_history: dict[str, list[ProbeResult]] = {}
        self._max_history_per_endpoint: int = 10

        # Consecutive success counters for threshold logic
        self._consecutive_successes: dict[str, int] = {}

        # Initialize provider types for all endpoints
        self._initialize_provider_types()

    def _initialize_provider_types(self) -> None:
        """Set provider type for all configured endpoints."""
        for instance_name, provider_cfg in self._config.providers.items():
            endpoints = provider_cfg.get_effective_endpoints()
            for idx in range(len(endpoints)):
                self._endpoint_manager.set_provider_type(
                    instance_name, str(idx), provider_cfg.type
                )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the health probing background task."""
        if self._running:
            return

        if not self._probe_config.enabled:
            logger.info("HealthMonitor disabled (probe_config.enabled=False)")
            return

        self._running = True
        self._probe_task = asyncio.create_task(self._probe_loop())
        logger.info(
            "HealthMonitor started with probe interval %ds",
            self._probe_config.probe_interval_seconds,
        )

    async def stop(self) -> None:
        """Stop the health probing background task."""
        self._running = False
        if self._probe_task:
            self._probe_task.cancel()
            try:
                await self._probe_task
            except asyncio.CancelledError:
                pass
        logger.info("HealthMonitor stopped")

    # ------------------------------------------------------------------
    # Probing
    # ------------------------------------------------------------------

    async def _probe_loop(self) -> None:
        """Main probing loop - probes inactive endpoints periodically."""
        # Initial delay to let the system settle
        await asyncio.sleep(5.0)

        while self._running:
            try:
                await self._probe_inactive_endpoints()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Probe loop error: %s", e)

            await asyncio.sleep(self._probe_config.probe_interval_seconds)

    async def _probe_inactive_endpoints(self) -> None:
        """Probe all currently inactive/unhealthy endpoints."""
        inactive_endpoints = self._endpoint_manager.get_all_inactive_endpoints()

        if not inactive_endpoints:
            logger.debug("No inactive endpoints to probe")
            return

        logger.debug("Probing %d inactive endpoints", len(inactive_endpoints))

        # Probe endpoints concurrently with timeout
        results = await asyncio.gather(
            *[
                self._probe_single_endpoint(ep)
                for ep in inactive_endpoints
            ],
            return_exceptions=True,
        )

        for result in results:
            if isinstance(result, Exception):
                logger.warning("Probe task raised exception: %s", result)
            elif isinstance(result, ProbeResult):
                self._process_probe_result(result)

    async def _probe_single_endpoint(
        self, endpoint_info: dict[str, Any]
    ) -> ProbeResult:
        """Execute a health probe for a single endpoint."""
        instance = endpoint_info["instance"]
        endpoint_index = endpoint_info["endpoint_index"]
        provider_type = endpoint_info["provider_type"]
        endpoint_key = endpoint_info["key"]

        # Mark as probing
        self._endpoint_manager.mark_probing(instance, endpoint_index)

        start_time = time.time()

        try:
            success, latency_ms = await asyncio.wait_for(
                self._health_checker.check_health(
                    instance,
                    provider_type,
                    endpoint_info.get("base_url"),
                    endpoint_info.get("api_key"),
                ),
                timeout=self._probe_config.probe_timeout_seconds,
            )

            # Record result in EndpointManager
            self._endpoint_manager.record_probe_result(
                instance, endpoint_index, success, latency_ms
            )

            return ProbeResult(
                endpoint_key=endpoint_key,
                instance=instance,
                endpoint_index=endpoint_index,
                provider_type=provider_type,
                success=success,
                latency_ms=latency_ms,
            )
        except asyncio.TimeoutError:
            latency_ms = self._probe_config.probe_timeout_seconds * 1000
            self._endpoint_manager.record_probe_result(
                instance, endpoint_index, False, 0.0
            )
            return ProbeResult(
                endpoint_key=endpoint_key,
                instance=instance,
                endpoint_index=endpoint_index,
                provider_type=provider_type,
                success=False,
                latency_ms=latency_ms,
                error_message="Probe timeout",
            )
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            self._endpoint_manager.record_probe_result(
                instance, endpoint_index, False, 0.0
            )
            return ProbeResult(
                endpoint_key=endpoint_key,
                instance=instance,
                endpoint_index=endpoint_index,
                provider_type=provider_type,
                success=False,
                latency_ms=latency_ms,
                error_message=str(e),
            )

    def _process_probe_result(self, result: ProbeResult) -> None:
        """Process probe result and update endpoint health."""
        endpoint_key = result.endpoint_key

        # Store in history
        history = self._probe_history.setdefault(endpoint_key, [])
        history.append(result)
        if len(history) > self._max_history_per_endpoint:
            history.pop(0)

        if result.success:
            # Increment consecutive success counter
            self._consecutive_successes[endpoint_key] = (
                self._consecutive_successes.get(endpoint_key, 0) + 1
            )

            # Check if we've reached threshold to mark healthy
            if self._consecutive_successes[endpoint_key] >= self._probe_config.success_threshold:
                self._endpoint_manager.mark_healthy(
                    result.instance, result.endpoint_index
                )
                logger.info(
                    "Endpoint %s recovered (latency: %.0fms)",
                    endpoint_key,
                    result.latency_ms,
                )
                # Reset counter after recovery
                self._consecutive_successes[endpoint_key] = 0
        else:
            # Reset success counter on failure
            self._consecutive_successes[endpoint_key] = 0
            logger.debug(
                "Endpoint %s still unhealthy: %s",
                endpoint_key,
                result.error_message or "probe failed",
            )

    async def probe_endpoint(
        self, instance: str, endpoint_index: str
    ) -> ProbeResult:
        """Manually trigger a probe for a specific endpoint (for testing/debugging)."""
        endpoint_info = self._endpoint_manager.get_endpoint_info(
            instance, endpoint_index
        )
        return await self._probe_single_endpoint(endpoint_info)

    # ------------------------------------------------------------------
    # Status & Introspection
    # ------------------------------------------------------------------

    def get_health_status(self) -> dict[str, Any]:
        """Get comprehensive health status for all endpoints."""
        return self._endpoint_manager.get_health_status()

    def get_probe_history(self, endpoint_key: str) -> list[ProbeResult]:
        """Get probe history for a specific endpoint."""
        return self._probe_history.get(endpoint_key, [])

    def is_running(self) -> bool:
        """Check if the health monitor is running."""
        return self._running

    def get_config(self) -> HealthProbeConfig:
        """Get the current probe configuration."""
        return self._probe_config