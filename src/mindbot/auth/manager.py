"""实时授权管理器 - Phase 2"""

import time
from dataclasses import dataclass, field
from typing import Any

from mindbot.config.bus import ConfigBus


@dataclass
class ToolAuth:
    tool_name: str
    allowed: bool
    expires_at: float | None = None
    granted_at: float = field(default_factory=time.time)

    def is_expired(self) -> bool:
        return self.expires_at is not None and time.time() > self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "allowed": self.allowed,
            "expires_at": self.expires_at,
            "granted_at": self.granted_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolAuth":
        return cls(
            tool_name=data["tool_name"],
            allowed=data["allowed"],
            expires_at=data.get("expires_at"),
            granted_at=data.get("granted_at", time.time()),
        )


class AuthManager:
    """实时授权管理器"""

    def __init__(self, bus: ConfigBus):
        self.bus = bus

    async def grant(
        self,
        user_id: str,
        tool_name: str,
        allowed: bool = True,
        expires_in: float | None = None,
    ) -> None:
        """授权/取消授权 - 立即生效"""
        expires_at = time.time() + expires_in if expires_in else None
        auth = ToolAuth(
            tool_name=tool_name,
            allowed=allowed,
            expires_at=expires_at,
        )

        scope = f"user:{user_id}"
        await self.bus.set(scope, f"auth:{tool_name}", auth)

    async def revoke(self, user_id: str, tool_name: str) -> None:
        """撤销授权"""
        scope = f"user:{user_id}"
        await self.bus.delete(scope, f"auth:{tool_name}")

    async def check(self, user_id: str, tool_name: str) -> tuple[bool, str]:
        """检查授权 - 实时查询"""
        scope = f"user:{user_id}"
        auth = await self.bus.get(scope, f"auth:{tool_name}")

        if auth is None:
            return False, "未授权"

        if isinstance(auth, dict):
            auth = ToolAuth(**auth)
        elif isinstance(auth, ToolAuth):
            pass
        else:
            return False, "授权数据格式错误"

        if auth.is_expired():
            return False, "授权已过期"

        return auth.allowed, "已授权" if auth.allowed else "已拒绝"

    async def list_user_auth(self, user_id: str) -> dict[str, ToolAuth]:
        """列出用户的所有授权"""
        scope = f"user:{user_id}"
        configs = self.bus.get_scope(scope)
        result = {}
        for key, value in configs.items():
            if key.startswith("auth:"):
                tool_name = key[5:]  # Remove 'auth:' prefix
                if isinstance(value, dict):
                    result[tool_name] = ToolAuth.from_dict(value)
                elif isinstance(value, ToolAuth):
                    result[tool_name] = value
        return result

    async def clear_user_auth(self, user_id: str) -> None:
        """清除用户的所有授权"""
        scope = f"user:{user_id}"
        configs = self.bus.get_scope(scope)
        for key in list(configs.keys()):
            if key.startswith("auth:"):
                await self.bus.delete(scope, key)
