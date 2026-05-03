"""Health check implementations for each provider type."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mindbot.config.schema import Config

from mindbot.logging import logger



class HealthCheckRegistry:
    """Registry of health check methods for different provider types.

    Each provider type has a specific health check method:
    - Ollama: GET /api/tags (lightweight, returns model list)
    - OpenAI: GET /v1/models (lightweight, returns available models)
    - Hailo: VDevice initialization attempt (heavier, but necessary)
    """

    def __init__(self, config: "Config") -> None:
        self._config = config
        self._checkers = {
            "ollama": self._check_ollama,
            "openai": self._check_openai,
            "hailo": self._check_hailo,
        }

    async def check_health(
        self,
        instance: str,
        provider_type: str,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> tuple[bool, float]:
        """Execute health check for the given provider type.

        Args:
            instance: Provider instance name (for logging)
            provider_type: Backend driver type (ollama, openai, hailo)
            base_url: API base URL (if applicable)
            api_key: API key (if applicable)

        Returns:
            tuple of (is_healthy: bool, latency_ms: float)
        """
        checker = self._checkers.get(provider_type)
        if not checker:
            logger.warning("No health checker for provider type: {}", provider_type)
            return True, 0.0  # Assume healthy if no checker

        start_time = time.time()
        try:
            result = await checker(instance, base_url, api_key)
            latency_ms = (time.time() - start_time) * 1000
            return result, latency_ms
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            logger.warning("Health check failed for {}: {}", instance, e)
            return False, latency_ms

    async def _check_ollama(
        self,
        instance: str,
        base_url: str | None,
        api_key: str | None,
    ) -> bool:
        """Check Ollama health via /api/tags endpoint."""
        import httpx

        if not base_url:
            base_url = "http://localhost:11434"

        base_url = base_url.rstrip("/")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                headers = {}
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"

                resp = await client.get(
                    f"{base_url}/api/tags",
                    headers=headers or None,
                )

                if resp.status_code == 200:
                    data = resp.json()
                    models = data.get("models", [])
                    logger.debug(
                        "Ollama %s healthy, %d models available", instance, len(models)
                    )
                    return True

                logger.warning(
                    "Ollama %s unhealthy: HTTP %d", instance, resp.status_code
                )
                return False
        except Exception as e:
            logger.warning("Ollama {} health check failed: {}", instance, e)
            return False

    async def _check_openai(
        self,
        instance: str,
        base_url: str | None,
        api_key: str | None,
    ) -> bool:
        """Check OpenAI-compatible health via /v1/models endpoint."""
        import httpx

        base_url = (base_url or "https://api.openai.com").rstrip("/")

        # If no API key and using OpenAI endpoint, skip (would fail auth)
        if "api.openai.com" in base_url and not api_key:
            logger.debug("OpenAI {}: skipping health check (no API key)", instance)
            return True  # Assume healthy, let actual requests verify

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                headers = {}
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"

                resp = await client.get(
                    f"{base_url}/v1/models",
                    headers=headers or None,
                )

                if resp.status_code == 200:
                    data = resp.json()
                    models = data.get("data", [])
                    logger.debug(
                        "OpenAI %s healthy, %d models available", instance, len(models)
                    )
                    return True

                # 401/403 might indicate API key issue, but endpoint is reachable
                if resp.status_code in (401, 403):
                    logger.debug("OpenAI {} reachable (auth error)", instance)
                    return True

                logger.warning(
                    "OpenAI %s unhealthy: HTTP %d", instance, resp.status_code
                )
                return False
        except Exception as e:
            logger.warning("OpenAI {} health check failed: {}", instance, e)
            return False

    async def _check_hailo(
        self,
        instance: str,
        base_url: str | None,
        api_key: str | None,
    ) -> bool:
        """Check Hailo health by attempting VDevice initialization.

        This is heavier than HTTP checks but necessary for hardware providers.
        Uses a quick device check without loading a model.
        """
        try:

            def _check_device() -> bool:
                try:
                    from hailo_platform import VDevice

                    vd = VDevice()
                    vd.release()
                    return True
                except Exception:
                    return False

            result = await asyncio.to_thread(_check_device)

            if result:
                logger.debug("Hailo {} healthy, device available", instance)
            else:
                logger.warning("Hailo {} unhealthy, device unavailable", instance)

            return result
        except ImportError:
            logger.warning("Hailo {}: hailo_platform not installed", instance)
            return True  # Assume healthy if library not available
        except Exception as e:
            logger.warning("Hailo {} health check failed: {}", instance, e)
            return False