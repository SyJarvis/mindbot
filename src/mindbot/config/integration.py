"""ConfigBus integration with Agent"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mindbot.config.bus import ConfigBus
from mindbot.config.persistence import ConfigPersistence
from mindbot.config.sync import ConfigSync
from mindbot.auth.manager import AuthManager

if TYPE_CHECKING:
    from mindbot.agent.orchestrator import AgentOrchestrator

logger = logging.getLogger(__name__)


class AgentConfigIntegration:
    """Agent 配置集成

    将 ConfigBus 集成到现有 Agent 架构中，提供：
    - 实时配置热更新
    - 授权实时生效
    - 配置持久化
    - 多实例同步（可选）

    Usage:
        # 在 Agent 初始化时创建
        self.config_integration = AgentConfigIntegration()
        await self.config_integration.initialize()

        # 获取配置
        temp = await self.config_integration.get("global", "temperature", 0.7)

        # 检查工具授权
        allowed, reason = await self.config_integration.check_auth(user_id, tool_name)
    """

    def __init__(
        self,
        bus: ConfigBus | None = None,
        persistence_path: Path | None = None,
        enable_persistence: bool = True,
        enable_sync: bool = False,
    ):
        self.bus = bus or ConfigBus()
        self.auth = AuthManager(self.bus)
        self._persistence: ConfigPersistence | None = None
        self._sync: ConfigSync | None = None
        self._enable_persistence = enable_persistence
        self._enable_sync = enable_sync
        self._persistence_path = persistence_path
        self._subscribed = False

    async def initialize(self) -> None:
        """初始化配置系统"""
        # 加载持久化配置
        if self._enable_persistence:
            path = self._persistence_path or Path.home() / ".mindbot" / "config_store.json"
            self._persistence = ConfigPersistence(self.bus, path)
            await self._persistence.load()
            await self._persistence.start()

        # 启动同步
        if self._enable_sync:
            self._sync = ConfigSync(self.bus)
            await self._sync.start()

        logger.info("AgentConfigIntegration initialized")

    async def shutdown(self) -> None:
        """关闭配置系统"""
        if self._persistence:
            await self._persistence.stop()
        if self._sync:
            await self._sync.stop()
        logger.info("AgentConfigIntegration shutdown")

    async def get(self, scope: str, key: str, default: Any = None) -> Any:
        """获取配置值"""
        return await self.bus.get(scope, key, default)

    async def set(self, scope: str, key: str, value: Any) -> None:
        """设置配置值"""
        await self.bus.set(scope, key, value)

    def subscribe(self, scope: str, key: str, callback: Any) -> None:
        """订阅配置变更"""
        self.bus.subscribe(scope, key, callback)

    async def check_auth(self, user_id: str, tool_name: str) -> tuple[bool, str]:
        """检查工具授权"""
        return await self.auth.check(user_id, tool_name)

    async def grant_auth(
        self,
        user_id: str,
        tool_name: str,
        allowed: bool = True,
        expires_in: float | None = None,
    ) -> None:
        """授权工具使用"""
        await self.auth.grant(user_id, tool_name, allowed, expires_in)

    def integrate_with_orchestrator(self, orchestrator: AgentOrchestrator) -> None:
        """集成到现有的 AgentOrchestrator

        这会将 ConfigBus 的授权检查与现有的 ApprovalManager 结合
        """
        # 订阅全局配置变更
        self.bus.subscribe("global", "temperature", self._on_temperature_change)
        self.bus.subscribe("global", "system_prompt", self._on_system_prompt_change)
        self._subscribed = True

    def _on_temperature_change(self, old: Any, new: Any) -> None:
        """温度配置变更回调"""
        logger.info(f"Temperature changed: {old} -> {new}")

    def _on_system_prompt_change(self, old: Any, new: Any) -> None:
        """系统提示词变更回调"""
        logger.info("System prompt updated")

    @property
    def version(self) -> int:
        """获取配置版本号"""
        return self.bus.version
